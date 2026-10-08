"""crb.factory.loop — the review comes before delivery, and a pull request's whole life.

Navigation
----------
What it is:   The factory loop's review-before-delivery and pull-request lifecycle tests, moved
              out of tests/test_factory_loop.py so the suite's shards stay inside their time
              budget (files are the shard unit).
What it does: Pins that the review comes BEFORE delivery and only an ``accept`` verdict reaches
              it (ADR-0021: a weak-oracle, rejected or rework-exhausted build opens no pull
              request and commits no delivery branch), that a rework delivers once after the
              final accept, that an item's pull request from an earlier run is updated on
              ``accept`` and CLOSED naming the verdict otherwise (a close that fails is a
              warning and never changes the item's status; a closed or merged pull request is
              never reopened), that a close asks for the same repository's credentials as a
              delivery, that an accept on another build's pack is refused before anything is
              pushed, and that neither a close nor a re-delivery reaches a repository the row
              was relinked to.
How:          The ``Rig`` and ``_rig`` harness of tests/test_factory_loop.py over ``pyrepo``,
              with ``MajorProbe`` / ``RejectingReviewer`` and a seeded open delivery.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0021-factory-review-before-delivery.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/factory/loop.py (under test), src/crb/factory/review.py and
              src/crb/factory/delivery.py (the steps it sequences), tests/test_factory_loop.py
              (the shared harness)
Tested by:    tests/test_factory_loop_pull_requests.py
Touch when:   never for a new repository; a delivery or close step is added to the loop, or the
              review's verdicts change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory import review as rv
from crb.factory.delivery import DeliveryError, GitCredentials, StaticProvider
from crb.observability.events import StepStatus
from fixtures import pyrepo as pr
from test_factory_build import MULTIPLY_HARDCODED, authored_multiply, multiply_item
from test_factory_loop import DELIVER_ROUTE, STRONGER_MULTIPLY, MultiBuilder, Rig, _creds, _rig

# --- C1: review before delivery; the PR never opens on an unreviewed build ----------


class MajorProbe:
    """A probe whose only finding is a ``major`` weak-oracle one — the mutation-strength
    probe's verdict on a weak test, without spending mutants."""

    name = "major_only"

    def run(self, ctx: rv.ReviewContext) -> rv.ProbeResult:
        return rv.ProbeResult(
            self.name,
            False,
            "weak",
            required=False,
            findings=(
                rv.ReviewFinding(
                    rv.FINDING_WEAK_ORACLE, rv.SEVERITY_MAJOR, "strengthen the test", self.name
                ),
            ),
        )


class RejectingReviewer(rv.MechanicalReviewer):
    name = "rejecting"

    def assess(self, ctx: Any, probes: Any) -> rv.ReviewOpinion:
        return rv.ReviewOpinion(rv.VERDICT_REJECT, summary="not this change")


def _crb_branches(pyrepo: pr.PyRepo) -> list[str]:
    """Every delivery branch (``crb/<item>-<slug>``) in the repository — a delivery commits
    on one before it pushes. The oracle's staging branches (``crb/factory/<item>/test``,
    build.py) are the factory's own and never pushed, so they are not counted."""
    out = pyrepo.repo.run("for-each-ref", "--format=%(refname)", "refs/heads/crb").stdout
    return [
        ln for ln in out.splitlines() if ln.strip() and not ln.startswith("refs/heads/crb/factory/")
    ]


def test_a_weak_oracle_verdict_never_reaches_delivery(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """C1 (assessment 2026-09-25): the loop delivered BEFORE it reviewed, so a pull request
    was public on a build whose test the review then found weak — and nothing closed it.
    Review comes first now: with ``MajorProbe`` no delivery call is made, the outcome is
    ``oracle_needs_strengthening``, no branch was pushed and none was even committed."""
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds(), probes=(MajorProbe(),))
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ORACLE_NEEDS_STRENGTHENING
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT]
    assert out.delivery is None and rig.pushes == [] and rig.prs == [] and rig.comments == []
    assert _crb_branches(pyrepo) == []
    kinds = rig.kinds("I-1")
    assert fe.EV_DELIVERY not in kinds and fe.EV_DELIVERY_UPDATED not in kinds
    # the review ran on a build nobody outside the factory has seen: no pull-request ref
    assert out.verdicts[0].pr_ref == ""
    assert not [e for e in rig.sink.events if e.action.startswith("delivery.")]


def test_a_rejected_build_is_never_delivered(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds(), reviewer=RejectingReviewer())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_REJECTED and out.delivery is None
    assert rig.pushes == [] and rig.prs == [] and _crb_branches(pyrepo) == []


def test_review_precedes_delivery_and_the_pull_request_carries_the_accepted_build(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The order on the chain is readiness → route → RED proof → build → verdict →
    delivery → outcome; the verdict that licenses the pull request is ``accept`` and its
    pack is the delivered one."""
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    assert rig.kinds("I-1") == [
        fe.EV_READINESS,
        fe.EV_ROUTE,
        fe.EV_RED_PROOF,
        fe.EV_BUILD,
        fe.EV_VERDICT,
        fe.EV_DELIVERY,
        fe.EV_ITEM_OUTCOME,
    ]
    (verdict,) = out.verdicts
    assert verdict.accepted and verdict.pack_hash == out.delivery.pack_hash
    actions = [e.action for e in rig.sink.events]
    assert actions.index("review.recorded") < actions.index("delivery.opened")


def test_a_rework_delivers_once_after_the_final_accept(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """accept_with_edit → rework → accept: ONE push, ONE pull request, opened after the
    second verdict on the reworked build — never a first PR on the build the review asked
    to change, then an update."""
    rig = _rig(
        pyrepo,
        tmp_path,
        builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED),
        rework_test=lambda item, verdict, previous: STRONGER_MULTIPLY,
        deliver=True,
        creds=_creds(),
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.reworks == 1
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT, rv.VERDICT_ACCEPT]
    assert [p["expected"] for p in rig.pushes] == [None] and len(rig.prs) == 1
    assert out.delivery is not None and not out.delivery.updated
    assert out.delivery.pack_hash == out.verdicts[-1].pack_hash
    kinds = rig.kinds("I-1")
    assert fe.EV_DELIVERY_UPDATED not in kinds
    assert kinds.count(fe.EV_DELIVERY) == 1
    last_verdict = len(kinds) - 1 - kinds[::-1].index(fe.EV_VERDICT)
    assert kinds.index(fe.EV_DELIVERY) > last_verdict


def test_rework_exhausted_opens_no_pull_request(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    class Opinionated(rv.MechanicalReviewer):
        name = "opinionated"

        def assess(self, ctx: Any, probes: Any) -> rv.ReviewOpinion:
            return rv.ReviewOpinion(
                rv.VERDICT_ACCEPT_WITH_EDIT,
                findings=(rv.ReviewFinding("naming", rv.SEVERITY_MAJOR, "rename the helper"),),
            )

    rig = _rig(pyrepo, tmp_path, reviewer=Opinionated(), deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_REWORK_EXHAUSTED and out.reworks == 1
    assert rig.pushes == [] and rig.prs == [] and out.delivery is None


def _seed_open_delivery(rig: Rig, *, pr_number: int = 5) -> dict[str, Any]:
    """An earlier run's delivery of ``I-1`` on the chain, its pull request still open."""
    from crb.factory.delivery import delivery_branch_name

    d = {
        "item_id": "I-1",
        "branch": delivery_branch_name(multiply_item()),
        "base": "main",
        "commit_sha": "c" * 40,
        # the shape GitHub answers with: the pull request's page in the repository it is in
        "pr_url": f"https://github.com/acme/calc/pull/{pr_number}",
        "pr_number": pr_number,
        "pack_hash": "p" * 64,
        "body_sha256": "",
        "created": "2026-09-20T00:00:00+00:00",
        "previous_commit_sha": "",
        "updated": False,
        "comment_error": "",
    }
    rig.evidence.record_delivery(d)
    return d


def test_an_open_pull_request_later_found_weak_is_closed_naming_the_verdict(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The rework path for a pull request an earlier run opened: when this run's review
    does not accept the item, the open pull request is CLOSED — with a comment naming the
    verdict and the finding — and the chain says the factory closed it; nothing is pushed."""
    closed: list[dict[str, Any]] = []

    def close_pr(**kw: Any) -> None:
        closed.append(kw)

    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        probes=(MajorProbe(),),
        close_pr_fn=close_pr,
    )
    _seed_open_delivery(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ORACLE_NEEDS_STRENGTHENING
    assert rig.pushes == [] and rig.prs == []
    (call,) = closed
    assert call["pr_number"] == 5 and call["remote"] == "https://github.com/acme/calc.git"
    assert "accept_with_edit" in call["body"] and rv.FINDING_WEAK_ORACLE in call["body"]
    (ev,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_CLOSED)
    assert ev.payload["pr_number"] == 5 and ev.payload["state"] == "closed"
    assert ev.payload["closed_by"] == "factory"
    assert ev.payload["verdict"] == rv.VERDICT_ACCEPT_WITH_EDIT
    # the close follows the verdict on the chain, and the item's outcome follows the close
    kinds = rig.kinds("I-1")
    assert kinds.index(fe.EV_VERDICT) < kinds.index(fe.EV_DELIVERY_CLOSED)
    assert kinds[-1] == fe.EV_ITEM_OUTCOME


def test_an_open_pull_request_re_accepted_is_updated_not_duplicated(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The other half: this run's build is accepted and the item already has an open pull
    request — the same PR is updated (lease against its commit), no second one opened."""
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    seeded = _seed_open_delivery(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    assert out.delivery.updated and out.delivery.pr_number == 5
    assert [p["expected"] for p in rig.pushes] == [seeded["commit_sha"]] and rig.prs == []


def test_a_closed_or_merged_pull_request_is_not_reopened_by_a_new_run(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    _seed_open_delivery(rig)
    rig.evidence.record_delivery_outcome("I-1", state="merged", pr_number=5)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    assert not out.delivery.updated and len(rig.prs) == 1


def test_a_close_that_fails_is_a_warning_and_never_changes_the_items_status(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """Closing an earlier run's pull request is the product's courtesy to the customer, not
    a step of the item: a close the forge refuses (or a seam that blows up) leaves the item's
    status as the review decided, the pull request open for the outcome sync to read, and a
    ``delivery.close_failed`` warning on the trace."""

    def broken_close(**kw: Any) -> None:
        raise RuntimeError("the forge answered 502")

    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        probes=(MajorProbe(),),
        close_pr_fn=broken_close,
    )
    _seed_open_delivery(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ORACLE_NEEDS_STRENGTHENING
    assert not rig.evidence.events_for("I-1", fe.EV_DELIVERY_CLOSED)
    (warn,) = [e for e in rig.sink.events if e.action == "delivery.close_failed"]
    assert warn.status == StepStatus.ERROR and "502" in (warn.error_message or "")


# --- the other final verdicts close an earlier run's open pull request too -----------


def _closing_rig(
    pyrepo: pr.PyRepo, tmp_path: Path, **overrides: Any
) -> tuple[Rig, list[dict[str, Any]]]:
    """A delivering rig whose close seam records its calls, with an earlier run's open
    pull request (number 5) for ``I-1`` already on the chain."""
    closed: list[dict[str, Any]] = []

    def close_pr(**kw: Any) -> None:
        closed.append(kw)

    overrides.setdefault("creds", _creds())
    rig = _rig(pyrepo, tmp_path, deliver=True, close_pr_fn=close_pr, **overrides)
    _seed_open_delivery(rig)
    return rig, closed


def _assert_closed_by_the_factory(
    rig: Rig, closed: list[dict[str, Any]], out: fl.ItemOutcome, verdict: str
) -> None:
    assert rig.pushes == [] and rig.prs == [] and rig.comments == [] and out.delivery is None
    (call,) = closed
    assert call["pr_number"] == 5 and f"`{verdict}`" in call["body"]
    (ev,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_CLOSED)
    assert ev.payload["pr_number"] == 5 and ev.payload["state"] == "closed"
    assert ev.payload["closed_by"] == "factory" and ev.payload["verdict"] == verdict
    kinds = rig.kinds("I-1")
    last_verdict = len(kinds) - 1 - kinds[::-1].index(fe.EV_VERDICT)
    assert last_verdict < kinds.index(fe.EV_DELIVERY_CLOSED) and kinds[-1] == fe.EV_ITEM_OUTCOME
    (sunk,) = [e for e in rig.sink.events if e.action == "delivery.closed"]
    assert sunk.status != StepStatus.ERROR


def test_an_open_pull_request_is_closed_when_this_runs_review_rejects_the_item(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """ADR-0021: an earlier run's open pull request is closed on ANY final verdict but
    ``accept`` — not only the weak-oracle stop. A ``reject`` closes it, naming the verdict,
    and nothing is pushed."""
    rig, closed = _closing_rig(pyrepo, tmp_path, reviewer=RejectingReviewer())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_REJECTED
    _assert_closed_by_the_factory(rig, closed, out, rv.VERDICT_REJECT)


def test_a_close_asks_for_the_same_repositorys_credentials_as_a_delivery(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """PR #55 review: the loop's close asked the credential provider for the ITEM id while
    its delivery asked for the repository, so a provider keyed on the repository resolved
    a close to the wrong key. Both now ask for the one repository key the loop holds."""
    asked: list[str] = []

    class Recording(StaticProvider):
        def resolve(self, repo: str) -> GitCredentials:
            """The provider must be asked for the repository key by both close and delivery:
            record each key asked for, then answer as the static provider."""
            asked.append(repo)
            return super().resolve(repo)

    creds = Recording(
        GitCredentials(remote="https://github.com/acme/calc.git", token="ghp_" + "b" * 36)
    )
    rig, closed = _closing_rig(pyrepo, tmp_path, reviewer=RejectingReviewer(), creds=creds)
    rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert len(closed) == 1
    rig2 = _rig(pyrepo, tmp_path / "b", deliver=True, creds=creds)
    out = rig2.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.delivery is not None
    assert asked == [str(pyrepo.repo.path)] * 2


def test_an_open_pull_request_is_closed_when_this_runs_rework_is_exhausted(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The same for a rework budget spent without an ``accept``: the last verdict is
    ``accept_with_edit`` and the open pull request is closed with it."""

    class Opinionated(rv.MechanicalReviewer):
        name = "opinionated"

        def assess(self, ctx: Any, probes: Any) -> rv.ReviewOpinion:
            return rv.ReviewOpinion(
                rv.VERDICT_ACCEPT_WITH_EDIT,
                findings=(rv.ReviewFinding("naming", rv.SEVERITY_MAJOR, "rename the helper"),),
            )

    rig, closed = _closing_rig(pyrepo, tmp_path, reviewer=Opinionated(), max_rework=1)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_REWORK_EXHAUSTED and out.reworks == 1
    _assert_closed_by_the_factory(rig, closed, out, rv.VERDICT_ACCEPT_WITH_EDIT)
    assert "naming" in closed[0]["body"]


def test_an_accept_on_another_builds_pack_is_refused_before_anything_is_pushed(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The verdict that licenses a delivery must be the review OF the build being
    delivered: an ``accept`` recorded for another pack (an earlier build, a rework's
    predecessor) is refused by the loop's own guard, before the route gate, a credential
    or a push — deliver() checks the verdict word, only the loop can check the pack."""
    from types import SimpleNamespace

    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    final: Any = SimpleNamespace(pack_hash="b" * 64)
    verdict = rv.ReviewVerdict(
        item_id="I-1",
        verdict=rv.VERDICT_ACCEPT,
        reviewer="mechanical",
        builder="fake/multi",
        test_author="operator",
        pack_hash="a" * 64,
        pr_ref="",
        red_reproduced=True,
    )
    with pytest.raises(DeliveryError, match="only an accepted, reviewed build"):
        rig.loop()._deliver(multiply_item(), final, DELIVER_ROUTE, verdict=verdict)
    assert rig.pushes == [] and rig.prs == [] and rig.comments == []
    assert not rig.evidence.events_for("I-1")


# --- PR #55 review: an earlier pull request is only ever touched in its own repository ------


def _relinked() -> StaticProvider:
    """Credentials for the repository the row is linked to NOW — another one than the
    earlier run delivered to (``link_repository`` lets an operator re-link a row)."""
    return StaticProvider(
        GitCredentials(remote="https://github.com/other/calc.git", token="ghp_" + "b" * 36)
    )


def test_a_close_never_reaches_a_pull_request_in_a_repository_the_row_was_relinked_to(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The chain keeps the earlier pull request's number; the credentials name the
    repository the row is linked to now. After a re-link, the close went to the SAME
    NUMBER in the new repository — somebody else's pull request, commented on and
    closed. The close now checks the repository the pull request was delivered to and
    refuses a different one: nothing is called, the warning names both repositories,
    and the chain records no close."""
    rig, closed = _closing_rig(pyrepo, tmp_path, reviewer=RejectingReviewer(), creds=_relinked())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_REJECTED
    assert closed == [] and rig.pushes == [] and rig.comments == []
    assert not rig.evidence.events_for("I-1", fe.EV_DELIVERY_CLOSED)
    (warn,) = [e for e in rig.sink.events if e.action == "delivery.close_failed"]
    said = warn.error_message or ""
    assert "acme/calc" in said and "other/calc" in said


def test_a_re_delivery_never_pushes_to_a_repository_the_row_was_relinked_to(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The accepted half: the re-delivery pushed the branch to the new repository and
    commented on the same-numbered pull request there. It is now refused before any
    push or comment, and the item stops as a failed delivery naming both repositories."""
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_relinked())
    _seed_open_delivery(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_DELIVERY_FAILED
    assert rig.pushes == [] and rig.prs == [] and rig.comments == []
    assert "acme/calc" in out.error and "other/calc" in out.error
