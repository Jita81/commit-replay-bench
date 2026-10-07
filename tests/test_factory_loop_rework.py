"""crb.factory.loop — rework after a review, and a weak oracle is never rebuilt against.

Navigation
----------
What it is:   The factory loop's rework tests, moved out of tests/test_factory_loop.py so the
              suite's shards stay inside their time budget (files are the shard unit).
What it does: Pins that accept-with-edit forces rework (RED → build → grade → fresh verdict →
              ONE pull request on the accepted rebuild) until the budget is exhausted, that a
              re-delivery whose pull-request comment fails is still updated (a warning, never
              a stop), that a ``weak_oracle`` verdict never rebuilds against an unchanged
              oracle (no test author, or one that returns the same bytes →
              ``oracle_needs_strengthening``, routed human with a reason whose prefix survives
              a 2000-char finding; DL-045 rule 3), and that a rework asked for another reason
              keeps the rework path.
How:          The ``Rig`` and ``_rig`` harness of tests/test_factory_loop.py over ``pyrepo``;
              the open-delivery seed from tests/test_factory_loop_pull_requests.py.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0021-factory-review-before-delivery.md
Works with:   src/crb/factory/loop.py (under test), src/crb/factory/review.py (the verdicts),
              src/crb/factory/delivery.py (the re-delivery), tests/test_factory_loop.py (the
              shared harness), tests/test_factory_loop_pull_requests.py (the seeded delivery)
Tested by:    tests/test_factory_loop_rework.py
Touch when:   never for a new repository; the rework budget rule or the weak-oracle rule
              (DL-045 rule 3) changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core.ledger import PROCESS_FACTORY, false_q1_total
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory import readiness as rd
from crb.factory import review as rv
from crb.factory.backlog import BacklogItem
from crb.factory.delivery import DeliveryError, GitCredentials, StaticProvider
from crb.factory.testfirst import AuthoredTest
from crb.observability.events import StepStatus
from fixtures import pyrepo as pr
from test_factory_build import (
    MULTIPLY_HARDCODED,
    OPERATOR,
    TEST_MULTIPLY_SRC,
    authored_multiply,
    multiply_item,
)
from test_factory_loop import MultiBuilder, Rig, _creds, _rig
from test_factory_loop_pull_requests import _crb_branches, _seed_open_delivery

# --- rework -------------------------------------------------------------------------


def test_accept_with_edit_forces_rework_red_build_grade_fresh_verdict(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    stronger = AuthoredTest(
        "tests/test_multiply.py",
        TEST_MULTIPLY_SRC + "\n\ndef test_multiply_other():\n    assert multiply(5, 6) == 30\n",
        OPERATOR,
    )
    edits: list[str] = []

    def rework_test(
        item: BacklogItem, verdict: rv.ReviewVerdict, previous: AuthoredTest
    ) -> AuthoredTest:
        edits.append(verdict.verdict)
        return stronger

    creds = StaticProvider(
        GitCredentials(remote="https://github.com/acme/calc.git", token="x" * 20)
    )
    rig = _rig(
        pyrepo,
        tmp_path,
        builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED),
        rework_test=rework_test,
        deliver=True,
        creds=creds,
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.reworks == 1
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT, rv.VERDICT_ACCEPT]
    assert edits == [rv.VERDICT_ACCEPT_WITH_EDIT]
    # ADR-0021: nothing was delivered until the rework's build was accepted — ONE push (a
    # first push, the bare lease), ONE pull request, carrying the reworked change
    assert [p["expected"] for p in rig.pushes] == [None]
    opened = rig.evidence.events_for("I-1", fe.EV_DELIVERY)
    assert len(opened) == 1 and len(rig.prs) == 1 and rig.comments == []
    assert out.delivery is not None and not out.delivery.updated
    assert out.delivery.pr_number == 1 and out.delivery.pr_url == opened[0].payload["pr_url"]
    assert out.delivery.pack_hash == out.verdicts[-1].pack_hash
    assert not rig.evidence.events_for("I-1", fe.EV_DELIVERY_UPDATED)
    assert [e.action for e in rig.sink.events if e.action.startswith("delivery.")] == [
        "delivery.opened",
    ]
    assert (
        pyrepo.repo.show_file(out.delivery.commit_sha, "tests/test_multiply.py") == stronger.content
    )
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha
    assert (
        out.proof is not None and out.proof.test_sha256 == stronger.sha256
    )  # the rework re-proved RED
    assert [b["trial"] for b in out.builds] == ["r1", "w1r1"]
    kinds = rig.kinds("I-1")
    # verdict → edit permitted → RED proof → build → fresh verdict → delivery, in that order
    v1 = kinds.index(fe.EV_VERDICT)
    assert kinds[v1 + 1] == fe.EV_EDIT
    assert kinds[v1 + 2] == fe.EV_RED_PROOF and fe.EV_BUILD in kinds[v1 + 2 :]
    assert kinds.count(fe.EV_VERDICT) == 2
    assert kinds[-3:] == [fe.EV_VERDICT, fe.EV_DELIVERY, fe.EV_ITEM_OUTCOME]
    assert rig.evidence.verify() == len(kinds)
    rows = list(rig.ledger.rows())
    assert len(rows) == 2 and all(r.process_step == PROCESS_FACTORY for r in rows)
    assert [r.trial for r in rows] == ["r1", "w1r1"] and false_q1_total(rows) == 0


def test_a_re_delivery_whose_pull_request_comment_fails_is_still_updated(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A re-delivery (the item's pull request an earlier run opened, accepted again —
    ADR-0021) posts its comment AFTER the lease push has moved the remote branch. When the
    comment fails (a rate limit, a 5xx, a timeout) the branch and the pull request already
    carry the new build: the loop must record `delivery.updated` (with the failure as
    ``comment_error``) and warn — never end the item `delivery_failed` with a
    `delivery.refused` that contradicts the remote."""
    from crb.factory.delivery import delivery_branch_name

    comments: list[dict[str, Any]] = []

    def failing_comment(**kw: Any) -> None:
        comments.append(kw)
        raise DeliveryError("GitHub comments API returned 403: rate limit exceeded")

    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds(), comment_pr_fn=failing_comment)
    seeded = _seed_open_delivery(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.error == ""
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT]
    assert [p["expected"] for p in rig.pushes] == [seeded["commit_sha"]] and rig.prs == []
    assert out.delivery is not None and out.delivery.updated
    assert out.delivery.commit_sha == pyrepo.repo.rev_parse(delivery_branch_name(multiply_item()))
    # the chain agrees with the remote: updated, with the comment failure on the event
    assert not rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    (updated,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_UPDATED)
    assert updated.payload["commit_sha"] == out.delivery.commit_sha
    assert updated.payload["previous_commit_sha"] == seeded["commit_sha"]
    assert updated.payload["body_sha256"] == "" and out.delivery.body_sha256 == ""
    assert updated.payload["comment_error"] == out.delivery.comment_error
    assert out.delivery.comment_error.startswith("DeliveryError: GitHub comments API returned 403")
    assert len(comments) == 1 and comments[0]["pr_number"] == 5
    assert "Rebuilt by a later factory run" in comments[0]["body"]
    # the step events: the update is recorded, the failed comment is a warning, not a stop
    steps = [e for e in rig.sink.events if e.action.startswith("delivery.")]
    assert [e.action for e in steps] == ["delivery.updated", "delivery.comment_failed"]
    assert steps[0].status == StepStatus.OK and steps[1].status == StepStatus.ERROR
    assert steps[1].error_message == out.delivery.comment_error
    assert steps[1].payload["pr"] == out.delivery.pr_url
    kinds = rig.kinds("I-1")
    # the seeded delivery, then this run: … verdict → re-delivery → outcome
    assert kinds[-3:] == [fe.EV_VERDICT, fe.EV_DELIVERY_UPDATED, fe.EV_ITEM_OUTCOME]
    assert rig.evidence.verify() == len(rig.evidence.events())


def _assert_stopped_for_a_stronger_oracle(rig: Rig, out: fl.ItemOutcome) -> None:
    """DL-045 rule 3, both halves: the item ends ``oracle_needs_strengthening`` with ONE
    build, ONE verdict and — since ADR-0021 — NO push and NO pull request (the review came
    first); the chain routes it human with the reviewer's finding in the reason; the trace
    carries ``rework.refused``."""
    assert out.status == fl.STATUS_ORACLE_NEEDS_STRENGTHENING and not out.accepted
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT]
    assert rig.builder.calls == 1 and [b["trial"] for b in out.builds] == ["r1"]
    assert rig.pushes == [] and rig.prs == [] and rig.comments == []
    assert out.delivery is None
    # the reason names the finding and the way forward, on the outcome and the chain
    assert out.error.startswith("the reviewer found the oracle weak (")
    assert "strengthen the test and register a superseding item" in out.error
    (finding,) = [f for f in out.verdicts[0].findings if f.kind == rv.FINDING_WEAK_ORACLE]
    assert finding.detail[:60] in out.error
    routes = rig.evidence.events_for("I-1", fe.EV_ROUTE)
    assert [r.payload["route"] for r in routes] == [rd.ROUTE_BUILD, rd.ROUTE_HUMAN]
    assert routes[-1].payload["reason"] == out.error
    assert routes[-1].payload["after_verdict"] == rv.VERDICT_ACCEPT_WITH_EDIT
    assert routes[-1].payload["finding"] == rv.FINDING_WEAK_ORACLE
    kinds = rig.kinds("I-1")
    assert kinds.count(fe.EV_BUILD) == 1 and kinds.count(fe.EV_VERDICT) == 1
    assert fe.EV_DELIVERY_UPDATED not in kinds and kinds.count(fe.EV_RED_PROOF) == 1
    assert kinds.index(fe.EV_VERDICT) < len(kinds) - 1 and kinds[-1] == fe.EV_ITEM_OUTCOME
    (outcome,) = rig.evidence.events_for("I-1", fe.EV_ITEM_OUTCOME)
    assert outcome.payload["status"] == fl.STATUS_ORACLE_NEEDS_STRENGTHENING
    assert outcome.payload["error"] == out.error and outcome.payload["builds"] == 1
    assert rig.evidence.verify() == len(kinds)
    decided = [e for e in rig.sink.events if e.action == "route.decided"]
    assert [e.payload["route"] for e in decided] == [rd.ROUTE_BUILD, rd.ROUTE_HUMAN]
    assert decided[-1].payload["reason"] == out.error
    (refused,) = [e for e in rig.sink.events if e.action == "rework.refused"]
    assert refused.status == StepStatus.SKIPPED and refused.payload["reason"] == out.error
    assert [e.action for e in rig.sink.events if e.action.startswith("delivery.")] == []
    assert [e.action for e in rig.sink.events].count("build.start") == 1
    assert [e.action for e in rig.sink.events][-1] == "item.done"


def test_weak_oracle_without_a_test_author_stops_before_any_rebuild(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """DL-045 rule 3 (B-1b finding 3): the reviewer's ``weak_oracle`` finding asks for a
    stronger TEST, and this deployment has no test author to write one — a rebuild against
    the same oracle would only let the builder find another way to pass it. The item stops:
    no edit permitted, no second RED proof, no second build, no second push; routed human
    with the finding and the way forward."""
    rig = _rig(
        pyrepo,
        tmp_path,
        builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED),  # weak_oracle → accept_with_edit
        deliver=True,
        creds=_creds(),
    )
    assert rig.spec.rework_test is None and rig.spec.max_rework == 1
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    _assert_stopped_for_a_stronger_oracle(rig, out)
    assert out.reworks == 0 and not rig.evidence.edits_for("I-1")
    assert not [e for e in rig.sink.events if e.action == "rework.start"]
    # ADR-0021: the weak build was never committed on a delivery branch, let alone pushed
    assert out.delivery is None and _crb_branches(pyrepo) == []


@pytest.mark.parametrize("returns", ["same_bytes", "none"])
def test_weak_oracle_with_a_test_author_returning_the_same_oracle_stops(
    pyrepo: pr.PyRepo, tmp_path: Path, returns: str
) -> None:
    """With a test author, the rework is allowed to ASK for a stronger test — but the
    oracle's sha256 must differ before any build: the same bytes back (or ``None`` = keep
    the previous test) is the same stop."""
    previous = authored_multiply()
    asked: list[str] = []

    def rework_test(
        item: BacklogItem, verdict: rv.ReviewVerdict, prev: AuthoredTest
    ) -> AuthoredTest | None:
        asked.append(verdict.verdict)
        assert prev.sha256 == previous.sha256
        if returns == "none":
            return None
        return AuthoredTest(prev.path, prev.content, "author-rung")  # same bytes, new author

    rig = _rig(
        pyrepo,
        tmp_path,
        builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED),
        rework_test=rework_test,
        deliver=True,
        creds=_creds(),
    )
    out = rig.loop().run_item(multiply_item(), authored=previous)
    _assert_stopped_for_a_stronger_oracle(rig, out)
    # the author WAS asked (the edit was permitted, the rework started) and answered with
    # the same oracle — so the rework is refused before its RED proof and build
    assert asked == [rv.VERDICT_ACCEPT_WITH_EDIT] and out.reworks == 1
    assert len(rig.evidence.edits_for("I-1")) == 1
    (start,) = [e for e in rig.sink.events if e.action == "rework.start"]
    assert start.payload["n"] == 1
    routes = rig.evidence.events_for("I-1", fe.EV_ROUTE)
    assert routes[-1].payload["oracle_sha256"] == previous.sha256
    assert "the test author returned the same oracle" in out.error


def test_a_long_weak_oracle_finding_keeps_the_reasons_prefix_and_way_forward(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The stop's reason is composed from the finding's detail — which may be the full 2000
    chars a ``ReviewFinding`` allows — and ``ItemOutcome.error`` is tail-capped at 2000. The
    loop caps the detail's HEAD when it composes the reason, so the prefix ("the reviewer
    found the oracle weak (") and the way forward survive on the outcome exactly as the
    chain and the trace carry them, whatever the detail's length."""
    long_detail = "operator " + "x" * 1991  # exactly the 2000 a ReviewFinding allows

    class VerboseReviewer(rv.MechanicalReviewer):
        name = "verbose"

        def assess(self, ctx: Any, probes: Any) -> rv.ReviewOpinion:
            return rv.ReviewOpinion(
                rv.VERDICT_ACCEPT_WITH_EDIT,
                findings=(
                    rv.ReviewFinding(rv.FINDING_WEAK_ORACLE, rv.SEVERITY_MAJOR, long_detail),
                ),
                summary="the oracle is weak",
            )

    rig = _rig(pyrepo, tmp_path, reviewer=VerboseReviewer(), deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    _assert_stopped_for_a_stronger_oracle(rig, out)
    (finding,) = [f for f in out.verdicts[0].findings if f.kind == rv.FINDING_WEAK_ORACLE]
    assert len(finding.detail) == 2000
    assert len(out.error) < 2000  # never tail-capped: the prefix is the reader's key
    assert out.error.startswith("the reviewer found the oracle weak (operator xxx")
    assert out.error.endswith(
        " …) and this deployment has no test author: "
        "strengthen the test and register a superseding item"
    )
    assert finding.detail not in out.error  # the head of the detail, not all of it


def test_rework_asked_for_a_reason_other_than_the_oracle_keeps_the_rework_path(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """Rule 3 is about the ORACLE: an ``accept_with_edit`` whose findings carry no
    ``weak_oracle`` (a reviewer's own major finding on the change) reworks as before — the
    same oracle, a fresh RED proof, a second build, a fresh verdict."""

    class OpinionatedReviewer(rv.MechanicalReviewer):
        name = "opinionated"

        def assess(self, ctx: Any, probes: Any) -> rv.ReviewOpinion:
            base = super().assess(ctx, probes)
            if any(f.kind == rv.FINDING_WEAK_ORACLE for p in probes for f in p.findings):
                return base
            return rv.ReviewOpinion(
                rv.VERDICT_ACCEPT_WITH_EDIT,
                findings=(rv.ReviewFinding("naming", rv.SEVERITY_MAJOR, "rename the helper"),),
                summary="rename the helper",
            )

    rig = _rig(pyrepo, tmp_path, reviewer=OpinionatedReviewer(), deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    # the loop reworked once (same oracle: a clean build, the map's probes pass) and the
    # reviewer asked again: the budget ends it, never rule 3
    assert out.status == fl.STATUS_REWORK_EXHAUSTED and out.reworks == 1
    # ADR-0021: an item that ends rework_exhausted opened no pull request at all
    assert rig.builder.calls == 2 and rig.pushes == [] and rig.prs == []
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT] * 2
    assert all(f.kind != rv.FINDING_WEAK_ORACLE for v in out.verdicts for f in v.findings)
    assert not [e for e in rig.sink.events if e.action == "rework.refused"]
    assert [r.payload["route"] for r in rig.evidence.events_for("I-1", fe.EV_ROUTE)] == [
        rd.ROUTE_BUILD
    ]


def test_rework_exhausted_when_no_budget(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path, builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED), max_rework=0)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_REWORK_EXHAUSTED and out.reworks == 0
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT]
    assert not rig.evidence.edits_for("I-1")
