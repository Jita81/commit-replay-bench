"""crb.factory.loop — one item end to end, and a frozen backlog under the all-comers rule.

Navigation
----------
What it is:   The factory loop's test suite — one item end to end, and a frozen backlog under
              the all-comers rule.
What it does: Pins that a spec refuses a test author that is also a rung, that a single item is
              accepted with delivery off by default, that an unsigned structural gap is refused
              and recorded, that an operator item is routed human not built, the test-first route
              through the author rung, that no oracle means no build, that a green authored test
              is not RED, that a not-clean build stops before review and delivery, that delivery
              on fails closed without credentials and otherwise opens a branch + PR after the
              review accepts, that the route gate reads the capability map ONCE per item at
              readiness — before any build — and the PR body quotes that reading (DL-045), that
              an approver's override is on the record and never the run's own actor, that a
              change larger than its licence is withheld, the full loop on a frozen backlog, and
              the ledgered horizon checkpoint. Rework and the weak-oracle rule live in
              tests/test_factory_loop_rework.py, review-before-delivery and a pull request's
              whole life in tests/test_factory_loop_pull_requests.py (the file was split so the
              suite's shards stay inside their time budget — files are the shard unit).
How:          ``Rig`` wires ``MultiBuilder`` (edit picked from the brief's subject; can misbehave
              once), ``FakeTestAuthor``, a ``MemorySink`` emitter, static credentials and
              recording push / PR / comment seams over ``pyrepo``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md,
              docs/adr/0021-factory-review-before-delivery.md
Works with:   src/crb/factory/loop.py (under test), src/crb/factory/readiness.py (the DoR
              gate), src/crb/factory/build.py, src/crb/factory/delivery.py and
              src/crb/factory/review.py (the steps it sequences), src/crb/factory/evidence.py
              (the factory evidence chain), tests/test_factory_build.py (the shared harness),
              tests/test_factory_loop_rework.py and tests/test_factory_loop_pull_requests.py
              (the two modules split from this one, which import its harness)
Tested by:    tests/test_factory_loop.py
Touch when:   never for a new repository; a step is added to the loop (a stop-before case and an
              end-to-end case).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from crb.builders.base import BuildBrief, BuildOutcome, Rung
from crb.builders.brief import ARM_S2
from crb.core.execution import LocalExecutor
from crb.core.ledger import PROCESS_FACTORY, JsonlLedger, false_q1_total
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory import readiness as rd
from crb.factory import review as rv
from crb.factory.backlog import KIND_CODE, KIND_OPERATOR, Backlog, BacklogError, BacklogItem
from crb.factory.delivery import GitCredentials, StaticProvider
from crb.factory.standard import CellRef, Readers, Standard
from crb.factory.testfirst import AuthoredTest, SameIdentityError
from crb.observability.events import Emitter, MemorySink
from fixtures import pyrepo as pr
from test_factory_build import (
    DIVIDE_DEF,
    MULTIPLY_DEF,
    MULTIPLY_HARDCODED,
    OPERATOR,
    TEST_DIVIDE,
    TEST_DIVIDE_SRC,
    TEST_MULTIPLY_SRC,
    FakeBuilder,
    append_src,
    authored_multiply,
    multiply_item,
    noop,
)

POWER_DEF = "\n\ndef power(a: int, b: int) -> int:\n    return a**b\n"
TEST_POWER = "tests/test_power.py"
TEST_POWER_SRC = "from calc import power\n\n\ndef test_power():\n    assert power(2, 3) == 8\n"

EDITS = {"multiply": MULTIPLY_DEF, "divide": DIVIDE_DEF, "power": POWER_DEF}

#: The operator's multiply oracle with one more case — a CHANGED oracle (a different
#: sha256), which is what lets a rework after a ``weak_oracle`` verdict proceed (DL-045 rule 3).
STRONGER_MULTIPLY = AuthoredTest(
    "tests/test_multiply.py",
    TEST_MULTIPLY_SRC + "\n\ndef test_multiply_other():\n    assert multiply(5, 6) == 30\n",
    OPERATOR,
)


@dataclass
class MultiBuilder(FakeBuilder):
    """Picks the source edit from the brief's subject; can misbehave on the first call."""

    name: str = "fake"
    model: str = "multi"
    first_edit: str = ""
    calls: int = 0

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Any, *, on_event: Any = None
    ) -> BuildOutcome:
        self.calls += 1
        text = self.first_edit if (self.first_edit and self.calls == 1) else ""
        if not text:
            for key, defn in EDITS.items():
                if key in brief.subject.lower():
                    text = defn
        self.edit = append_src(text) if text else noop
        return super().build(workspace, brief, budget, on_event=on_event)


@dataclass
class FakeTestAuthor:
    """A test author that returns a scripted ``(path, content)`` per item id."""

    name: str = "author"
    model: str = "t1"
    provider: str = "fake"
    tests: dict[str, tuple[str, str]] = field(
        default_factory=lambda: {
            "I-2": (TEST_DIVIDE, TEST_DIVIDE_SRC),
            "I-3": (TEST_POWER, TEST_POWER_SRC),
        }
    )
    calls: list[str] = field(default_factory=list)

    def author(
        self,
        workspace: Workspace,
        item: BacklogItem,
        *,
        facts: Mapping[str, str],
        config: RepoConfig,
        on_event: Any = None,
    ) -> AuthoredTest:
        self.calls.append(item.id)
        path, content = self.tests[item.id]
        return AuthoredTest(path, content, "claimed")

    def describe(self) -> dict[str, Any]:
        return {"author": self.name}


def _items() -> tuple[BacklogItem, ...]:
    return (
        multiply_item(),  # I-1: every slot filled → build route; operator-authored test
        BacklogItem(
            id="I-2",
            title="Add divide to calc",
            kind=KIND_CODE,
            capability_class="bug.fix",
            structural_facts=(
                "reproduction: `from calc import divide` raises ImportError",
                "expected_behaviour: calc exposes divide(a, b) -> float",
            ),  # value slot open → test_first_authoring
            depends_on=("I-1",),
        ),
        BacklogItem(
            id="I-3",
            title="Add power to calc",
            kind=KIND_CODE,
            capability_class="bug.fix",
            structural_facts=("reproduction: no power()", "expected_behaviour: power(a, b) -> int"),
        ),
        BacklogItem(
            id="I-4",
            title="Add a health route",
            kind=KIND_CODE,
            capability_class="backend.route.add",
            structural_facts=("method_path: GET /health",),  # unsigned structural gaps
        ),
        BacklogItem(
            id="I-5",
            title="Buy the domain",
            kind=KIND_OPERATOR,
            capability_class="infra.terraform.edit",
        ),
        BacklogItem(
            id="I-6",
            title="Route needs health",
            kind=KIND_CODE,
            capability_class="bug.fix",
            depends_on=("I-4",),
        ),
    )


@dataclass
class Rig:
    """Everything one loop run needs, wired: the spec, the sink, the evidence chain, the ledger, the
    fakes and the recorded delivery seams.
    """

    repo: pr.PyRepo
    spec: fl.FactorySpec
    sink: MemorySink
    evidence: fe.FactoryEvidence
    ledger: JsonlLedger
    builder: MultiBuilder
    author: FakeTestAuthor
    pushes: list[dict[str, Any]]
    prs: list[dict[str, Any]]
    comments: list[dict[str, Any]]

    def loop(self) -> fl.FactoryLoop:
        """A ``FactoryLoop`` over the rig's spec with an emitter into its sink."""
        return fl.FactoryLoop(
            self.spec, self.repo.repo, emitter=Emitter(self.sink, actor="tester", repo="pyrepo")
        )

    def kinds(self, item_id: str) -> list[str]:
        """The factory-evidence event kinds recorded for ``item_id``, in order."""
        return [e.kind for e in self.evidence.events_for(item_id)]


def _rig(pyrepo: pr.PyRepo, tmp_path: Path, **overrides: Any) -> Rig:
    sink = MemorySink()
    evidence = fe.FactoryEvidence(
        fe.JsonlFactoryStore(tmp_path / "evidence.jsonl"), actor="tester", repo="pyrepo"
    )
    ledger = JsonlLedger(tmp_path / "grades.jsonl")
    builder = overrides.pop("builder", MultiBuilder())
    author = overrides.pop("author", FakeTestAuthor())
    pushes: list[dict[str, Any]] = []
    prs: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []

    def push(
        repo: Any,
        *,
        branch: str,
        refspec: str,
        credentials: GitCredentials,
        expected: str | None = None,
    ) -> None:
        pushes.append({"branch": branch, "refspec": refspec, "expected": expected})

    def open_pr(**kw: Any) -> tuple[str, int]:
        prs.append(kw)
        return f"https://github.invalid/pr/{len(prs)}", len(prs)

    def comment_pr(**kw: Any) -> None:
        comments.append(kw)

    kw: dict[str, Any] = {
        "config": pyrepo.config,
        "runner": PytestRunner(pyrepo.config),
        "executor": LocalExecutor(),
        "scratch": tmp_path / "scratch",
        "evidence_dir": tmp_path / "packs",
        "evidence": evidence,
        "ledger": ledger,
        "ladder": (Rung("fake", "multi"),),
        "builder_for": lambda r: builder,
        "reviewer": rv.MechanicalReviewer(),
        "test_author": author,
        "gap_ledger": rd.JsonlGapSignoffLedger(tmp_path / "gaps.jsonl"),
        "push_fn": push,
        "open_pr_fn": open_pr,
        "comment_pr_fn": comment_pr,
        "run_id": "run-1",
        "actor": "tester",
        # the route gate: delivery tests that want a PR must say the cell routes `deliver`
        # (the map's word), the way the worker feeds the map's decision to the loop
        "route_decision_for": lambda item: DELIVER_ROUTE,
        # the entry gate (ADR-0026 item 8): every cell here has a proven, signed standard —
        # S2 (a person's test) for XS, where the operator-authored multiply item sits, and
        # S1 on the fake author for the rest; a test of the gate passes its own readers
        "readers": PROVEN,
    }
    kw.update(overrides)
    return Rig(
        pyrepo, fl.FactorySpec(**kw), sink, evidence, ledger, builder, author, pushes, prs, comments
    )


#: A capability-map decision as the worker hands it to the loop (``RouteDecision.to_dict``).
DELIVER_ROUTE: dict[str, Any] = {
    "route": "deliver",
    "reason": "n=12 point=1.000 ci_low=0.76 false_q1=0",
    "reason_code": "deliver",
    "policy_version": "routing.v1",
    "n": 12,
    "point": 1.0,
    "ci_low": 0.76,
    "false_q1": 0,
    "apparatus_versions": ["2.2"],
    "policy_thresholds": {"min_n": 10},  # not part of the evidence summary
}
HUMAN_ROUTE: dict[str, Any] = {
    "route": "human",
    "reason": "oracle strength 0.58 < 0.80 — green cannot license auto-delivery",
    "reason_code": "oracle_weak",
    "policy_version": "routing.v1",
    "n": 12,
}


def _proven(cell: CellRef) -> Standard:
    return Standard(ARM_S2 if cell.size == "XS" else "S1@t1", signed=True)


#: A proven, signed standard in every cell (the gate's own tests pass their own readers).
PROVEN = Readers(standard_for=_proven)


# --- spec guards ------------------------------------------------------------------


def test_spec_refuses_test_author_that_is_also_a_rung(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with pytest.raises(SameIdentityError):
        _rig(pyrepo, tmp_path, ladder=(Rung("author", "t1"),))
    with pytest.raises(ValueError):
        _rig(pyrepo, tmp_path, ladder=())


# --- one item ---------------------------------------------------------------------


def test_single_item_accepted_delivery_off_by_default(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.accepted
    assert out.readiness is not None and out.readiness.route_hint == rd.ROUTE_BUILD
    assert out.proof is not None and out.proof.author == OPERATOR
    assert len(out.builds) == 1 and out.builds[0]["clean"] and out.builds[0]["rung"] == "fake:multi"
    assert out.delivery is None and not rig.pushes and not rig.prs
    assert (
        out.final_verdict is not None
        and out.final_verdict.accepted
        and out.final_verdict.pr_ref == ""
    )
    # ADR-0021: the review precedes the delivery step (here: the opt-in refusal)
    assert rig.kinds("I-1") == [
        fe.EV_READINESS,
        fe.EV_ROUTE,
        fe.EV_RED_PROOF,
        fe.EV_BUILD,
        fe.EV_VERDICT,
        fe.EV_DELIVERY_REFUSED,
        fe.EV_ITEM_OUTCOME,
    ]
    refused = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[0]
    assert "opt-in" in refused.payload["reason"]
    assert rig.evidence.verify() == 7
    rows = list(rig.ledger.rows())
    assert len(rows) == 1 and rows[0].process_step == PROCESS_FACTORY and rows[0].clean
    assert false_q1_total(rows) == 0
    # observability: every event is stage=factory, bound to the item, and the workspaces are gone
    evs = rig.sink.events
    assert evs and all(e.stage == "factory" for e in evs)
    # factory-level events are bound to the item; the core grader's own events to the oracle commit
    assert {e.task_id for e in evs} == {"I-1", out.builds[0]["oracle_commit"]}
    actions = [e.action for e in evs]
    assert actions[0] == "item.start" and actions[-1] == "item.done"
    assert "red.proved" in actions and "grade.belt" in actions and "review.verdict" in actions
    assert not any((tmp_path / "scratch").glob("build-*"))
    assert out.to_dict()["status"] == "accepted"


def test_unsigned_structural_gap_is_refused_and_recorded(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path)
    item = _items()[3]
    out = rig.loop().run_item(item)
    # ADR-0026 item 8: the cell's standard is S1, which needs the structural facts the test
    # author reads — a ticket missing them stops `needs_context`, naming them, before spend
    assert out.status == fl.STATUS_NEEDS_CONTEXT and out.proof is None and not out.builds
    assert out.readiness is not None and {g.slot for g in out.readiness.blocking_gaps} == {
        "request_shape",
        "response_shape",
        "error_contract",
    }
    assert rig.kinds("I-4") == [
        fe.EV_READINESS,
        fe.EV_ENTRY_REFUSED,
        fe.EV_ROUTE,
        fe.EV_ITEM_OUTCOME,
    ]
    refused = rig.evidence.events_for("I-4", fe.EV_ENTRY_REFUSED)[0].payload
    assert set(refused["needs"]) == {"request_shape", "response_shape", "error_contract"}
    assert rig.evidence.events_for("I-4", fe.EV_ROUTE)[0].payload["route"] == rd.ROUTE_HUMAN
    assert rig.builder.calls == 0 and not rig.author.calls
    # sign the gaps → the same item now builds (with a test the author supplies)
    gl = rig.spec.gap_ledger
    assert gl is not None
    for slot, ans in (
        ("request_shape", "none"),
        ("response_shape", "200 {status}"),
        ("error_contract", "none"),
    ):
        rd.sign(gl, item, slot, ans, verifier="po@example")
    r = rd.assess(item, gl.for_item(item.id))
    assert r.ready and r.route_hint == rd.ROUTE_TEST_FIRST


def test_operator_item_is_routed_human_not_built(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path)
    out = rig.loop().run_item(_items()[4])
    assert out.status == fl.STATUS_ROUTED_HUMAN
    assert rig.evidence.events_for("I-5", fe.EV_ROUTE)[0].payload["route"] == rd.ROUTE_HUMAN
    assert rig.builder.calls == 0


def test_test_first_route_uses_the_author_rung(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path)
    out = rig.loop().run_item(_items()[1])
    assert out.status == fl.STATUS_ACCEPTED
    assert out.readiness is not None and out.readiness.route_hint == rd.ROUTE_TEST_FIRST
    assert rig.author.calls == ["I-2"]
    assert (
        out.proof is not None
        and out.proof.author == "author:t1"
        and out.proof.test_path == TEST_DIVIDE
    )
    assert out.final_verdict is not None and out.final_verdict.test_author == "author:t1"


def test_no_oracle_when_no_test_and_no_author(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path, test_author=None)
    # an S1 cell (the rig's standard for S): the arm's oracle is the test author's, and
    # there is none
    out = rig.loop().run_item(multiply_item(size_estimate="S"), authored=authored_multiply())
    assert out.status == fl.STATUS_NO_ORACLE
    assert rig.evidence.events_for("I-1", fe.EV_RED_REFUSED)


def test_green_authored_test_is_not_red(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path)
    green = AuthoredTest(
        "tests/test_multiply.py",
        "from calc import add\n\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        OPERATOR,
    )
    out = rig.loop().run_item(multiply_item(), authored=green)
    assert out.status == fl.STATUS_NOT_RED and "GREEN" in out.error
    assert rig.kinds("I-1") == [fe.EV_READINESS, fe.EV_ROUTE, fe.EV_RED_REFUSED, fe.EV_ITEM_OUTCOME]
    assert rig.builder.calls == 0


def test_not_clean_build_stops_before_delivery_and_review(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(
        pyrepo, tmp_path, builder=MultiBuilder(first_edit="\n# nothing useful\n"), deliver=True
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_NOT_CLEAN and not out.verdicts and out.delivery is None
    assert not rig.pushes
    rows = list(rig.ledger.rows())
    assert len(rows) == 1 and not rows[0].clean and rows[0].process_step == PROCESS_FACTORY


# --- delivery opt-in ----------------------------------------------------------------


def test_delivery_on_fails_closed_without_credentials(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path, deliver=True)  # no creds → NullProvider
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_DELIVERY_FAILED and "fail closed" in out.error
    # ADR-0021: the build was reviewed and accepted first; only then did delivery fail closed
    assert not rig.pushes and not rig.prs
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT]
    assert rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha


def test_delivery_on_opens_branch_and_pr_after_the_review_accepts(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    creds = StaticProvider(
        GitCredentials(remote="https://github.com/acme/calc.git", token="ghp_" + "b" * 36)
    )
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=creds, target_default_branch="main")
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    assert out.delivery.branch == "crb/i-1-add-multiply-to-calc" and out.delivery.base == "main"
    assert rig.pushes == [
        {
            "branch": out.delivery.branch,
            "refspec": f"{out.delivery.branch}:{out.delivery.branch}",
            "expected": None,
        }
    ]
    # ADR-0021: the review ran before any pull request existed, and licensed the one opened
    assert out.final_verdict is not None and out.final_verdict.accepted
    assert out.final_verdict.pr_ref == ""
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha  # never main
    kinds = rig.kinds("I-1")
    assert fe.EV_DELIVERY in kinds and kinds.index(fe.EV_VERDICT) < kinds.index(fe.EV_DELIVERY)


# --- the route gate (DL-038) --------------------------------------------------------


def _creds() -> StaticProvider:
    return StaticProvider(
        GitCredentials(remote="https://github.com/acme/calc.git", token="ghp_" + "b" * 36)
    )


def test_route_gate_withholds_delivery_when_the_cell_does_not_route_deliver(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The capability map decides what the factory may deliver: a clean build in a cell
    that routes `human` is built, graded and reviewed, but no branch is pushed and no PR
    opened; the withholding names the measured route on the evidence chain."""
    rig = _rig(
        pyrepo, tmp_path, deliver=True, creds=_creds(), route_decision_for=lambda item: HUMAN_ROUTE
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None  # reviewed, not delivered
    assert not rig.pushes and not rig.prs
    refused = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    assert len(refused) == 1
    ev = refused[0].payload
    assert ev["reason"].startswith("route gate: the cell routes human (oracle_weak)")
    assert ev["measured_route"] == "human" and ev["reason_code"] == "oracle_weak"
    assert ev["policy_version"] == "routing.v1"
    assert fe.EV_DELIVERY not in rig.kinds("I-1")
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha


def test_route_gate_withholds_delivery_when_nothing_is_measured(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds(), route_decision_for=None)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    ev = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[0].payload
    assert "no capability-map route" in ev["reason"] and ev["measured_route"] == ""


def test_route_gate_is_not_lifted_by_an_approvers_override(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """ADR-0026 item 8: ``deliver_override`` lifts the sign-off clause and nothing else — a
    cell whose route is not ``deliver`` still opens no pull request, override or not."""
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        route_decision_for=lambda item: HUMAN_ROUTE,
        deliver_override_by="approver:ada",
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    ev = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[0].payload
    assert ev["reason"].startswith("route gate: the cell routes human")


#: A cell the map refuses for the honesty floor: a clean row in it failed a belt (false-Q1).
FALSE_Q1_ROUTE: dict[str, Any] = {
    "route": "do_not_ship",
    "reason": "1 false-Q1 row(s) in cell — evidence untrusted",
    "reason_code": "false_q1",
    "policy_version": "routing.v1",
    "n": 12,
    "false_q1": 1,
}


def _unsigned_everywhere(cell: CellRef) -> Standard:
    """A proven standard nobody has signed, in every cell: the sign-off clause is the only
    stop, so an override is the only thing that can let the item in."""
    return Standard(ARM_S2 if cell.size == "XS" else "S1@t1", signed=False)


UNSIGNED = Readers(standard_for=_unsigned_everywhere)


def _override_refusals(rig: Rig) -> list[dict[str, Any]]:
    return [
        e.payload
        for e in rig.evidence.events_for("I-1", fe.EV_ROUTE)
        if e.payload.get("override_refused")
    ]


def _lifted(rig: Rig) -> list[dict[str, Any]]:
    return [
        e.payload
        for e in rig.evidence.events_for("I-1", fe.EV_ROUTE)
        if e.payload.get("override_by") and not e.payload.get("override_refused")
    ]


def test_no_override_lifts_anything_on_a_false_q1_cell(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """GOV-1 (governance review 2026-09-27) under ADR-0026 item 8: false-Q1 = 0 is the honesty
    floor. A sign-off can never lift a false-Q1 cell (``NON_OVERRIDABLE_REFUSALS``), and
    neither can the one-run override of the sign-off clause: the refusal on the chain names
    the floor and the approver whose override it refused, and the item stops unsigned before
    any spend — nothing built, nothing pushed."""
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: FALSE_Q1_ROUTE,
        deliver_override_by="approver:ada",
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_UNSIGNED_CELL and out.delivery is None
    assert not out.builds and not rig.pushes and not rig.prs
    (refused,) = _override_refusals(rig)
    assert refused["override_refused"] == "false_q1" and refused["override_by"] == "approver:ada"
    assert "false-Q1" in refused["reason"] and "no override" in refused["reason"]
    assert not _lifted(rig)  # nothing was lifted
    # a cell whose summary carries a false-Q1 row is held to the floor whatever its word
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: {**HUMAN_ROUTE, "false_q1": 2},
        deliver_override_by="approver:ada",
    )
    out2 = rig2.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out2.status == fl.STATUS_UNSIGNED_CELL and not rig2.prs
    assert _override_refusals(rig2)[-1]["override_refused"] == "false_q1"


def test_the_sign_off_override_is_never_the_runs_own_actor(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """GOV-4 under ADR-0026 item 8: the override lifts the sign-off clause, so — like a
    sign-off (ADR-0016) — it is never granted by the actor of the run that produces the
    evidence. The loop refuses it at the entry gate and records the refusal; an override read
    live at the gate (a second approver's act while the run works) is honoured, lifts only
    the sign-off, and never opens a pull request the route gate withholds."""
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
        deliver_override_by="tester",  # the rig's run actor
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_UNSIGNED_CELL and not out.builds and not rig.prs
    (refused,) = _override_refusals(rig)
    assert refused["override_refused"] == "same_actor" and refused["override_by"] == "tester"
    # the live seam: nobody granted when the loop was made, a second approver before the gate
    grants: list[str] = []
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: HUMAN_ROUTE,
        deliver_override_for=lambda: grants[-1] if grants else "",
    )
    loop2 = rig2.loop()
    grants.append("approver:grace")
    out2 = loop2.run_item(multiply_item(), authored=authored_multiply())
    assert out2.status == fl.STATUS_ACCEPTED and out2.builds  # the sign-off was lifted
    (lifted,) = _lifted(rig2)
    assert lifted["override_by"] == "approver:grace"
    # ... and only the sign-off: the route gate still withholds the pull request
    assert out2.delivery is None and not rig2.prs
    # the live seam naming the run's actor is refused the same way
    rig3 = _rig(
        pyrepo,
        tmp_path / "c",
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
        deliver_override_for=lambda: "tester",
    )
    out3 = rig3.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out3.status == fl.STATUS_UNSIGNED_CELL and not rig3.prs
    assert _override_refusals(rig3)[-1]["override_refused"] == "same_actor"


#: The person's test (``S2``) proven and signed in every cell, so the delivered change's own
#: licence holds at any size and the ROUTE decides (GOV-2's tests).
S2_EVERYWHERE = Readers(standard_for=lambda cell: Standard(ARM_S2, signed=True))


def _padded(n: int) -> tuple[str, AuthoredTest]:
    """A multiply edit padded with ``n`` extra functions (so the diff measures larger than
    XS) and the operator's oracle that exercises every one of them."""
    extra = "".join(f"\n\ndef pad_{i}(x: int) -> int:\n    return x + {i}\n" for i in range(n))
    names = ", ".join(f"pad_{i}" for i in range(n))
    oracle = AuthoredTest(
        "tests/test_multiply.py",
        f"from calc import multiply, {names}\n\n\ndef test_multiply():\n"
        "    assert multiply(3, 4) == 12\n\n\ndef test_pads():\n"
        + "".join(f"    assert pad_{i}(1) == {1 + i}\n" for i in range(n)),
        OPERATOR,
    )
    return MULTIPLY_DEF + extra, oracle


def test_a_change_larger_than_its_licence_is_withheld_size_exceeds_licence(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """GOV-2 (governance review 2026-09-27): the route gate read the cell of the item's
    DECLARED size (a ticket's story points); the build's row records the MEASURED size of
    the diff. A cell licensed for XS changes never licenses a larger one: the measured cell
    is read (from the same pre-run map) and, when it does not route ``deliver``, the item
    is withheld ``size_exceeds_licence`` with both sizes on the chain."""
    edit, oracle = _padded(12)
    reads: list[str] = []

    def route_for(item: BacklogItem) -> dict[str, Any] | None:
        reads.append(item.size_estimate)
        return DELIVER_ROUTE if item.size_estimate == "XS" else HUMAN_ROUTE

    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=S2_EVERYWHERE,
        route_decision_for=route_for,
    )
    item = multiply_item()
    assert item.size_estimate == "XS"
    out = rig.loop().run_item(item, authored=oracle)
    measured = [r for r in rig.ledger.rows() if r.clean][-1].size
    assert measured not in ("XS", "")  # the change that would be delivered is larger
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    assert reads == ["XS", measured]  # the declared cell at readiness, the measured one after
    (refused,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    ev = refused.payload
    assert ev["reason_code"] == "size_exceeds_licence"
    assert ev["size_estimate"] == "XS" and ev["size_measured"] == measured
    assert ev["measured_route"] == "human"
    # no override stretches an XS route over the measured cell's refusal (ADR-0026 item 8:
    # an override lifts the sign-off clause only, never the route gate)
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=S2_EVERYWHERE,
        route_decision_for=lambda item: (
            DELIVER_ROUTE if item.size_estimate == "XS" else FALSE_Q1_ROUTE
        ),
        deliver_override_by="approver:ada",
    )
    out2 = rig2.loop().run_item(multiply_item(), authored=oracle)
    assert out2.delivery is None and not rig2.prs


def test_a_change_smaller_than_its_estimate_is_licensed_by_its_own_measured_cell(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-335: the route gate re-read the measured cell only when the change measured LARGER
    than its estimate, so a change estimated S that measured XS was delivered on the S
    cell's route although the XS cell — the change's own — routed ``human`` (a weak oracle
    there). ``manufacture-and-deliver.truth.16`` and ADR-0025 item 12 name the measured
    cell's route whatever the direction: a smaller change whose cell does not route
    ``deliver`` is withheld with both sizes and the measured cell's own reason."""
    reads: list[str] = []

    def route_for(item: BacklogItem) -> dict[str, Any] | None:
        reads.append(item.size_estimate)
        return DELIVER_ROUTE if item.size_estimate == "S" else HUMAN_ROUTE

    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        readers=S2_EVERYWHERE,
        route_decision_for=route_for,
    )
    out = rig.loop().run_item(multiply_item(size_estimate="S"), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED, (out.status, out.error)
    measured = [r for r in rig.ledger.rows() if r.clean][-1].size
    assert measured == "XS"  # the change that would be delivered is smaller
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    assert reads == ["S", "XS"]  # the declared cell at readiness, the measured one after
    (refused,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    ev = refused.payload
    assert ev["reason_code"] == "oracle_weak" and ev["measured_route"] == "human"
    assert ev["size_estimate"] == "S" and ev["size_measured"] == "XS"
    # the same change in a measured cell that routes deliver is delivered
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        readers=S2_EVERYWHERE,
        route_decision_for=lambda item: DELIVER_ROUTE,
    )
    assert (
        rig2.loop()
        .run_item(multiply_item(size_estimate="S"), authored=authored_multiply())
        .delivery
        is not None
    )
    assert len(rig2.prs) == 1


def test_a_larger_change_is_delivered_when_its_measured_cell_routes_deliver(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """GOV-2: the licence is the measured cell's — when it routes ``deliver`` the pull
    request opens, its body names both sizes and quotes the measured cell's route."""
    edit, oracle = _padded(12)
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=S2_EVERYWHERE,
        route_decision_for=lambda item: {
            **DELIVER_ROUTE,
            "n": 30 if item.size_estimate != "XS" else 12,
        },
    )
    out = rig.loop().run_item(multiply_item(), authored=oracle)
    measured = [r for r in rig.ledger.rows() if r.clean][-1].size
    assert out.delivery is not None and len(rig.prs) == 1
    body = rig.prs[0]["body"]
    assert (
        f"- size: estimated `XS`, measured `{measured}` — licensed on the (`bug.fix`, "
        f"`{measured}`) cell" in body
    )
    assert "- route: **deliver**" in body


def test_route_is_read_once_per_item_at_readiness_before_any_build(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """DL-045 (B-1b finding 2): the map that licenses a delivery is the map as it stood
    BEFORE the run — read once per item at readiness, never after the item's own row has
    landed; the gate and the PR body use that one reading, and the ``route.decided`` event
    records it (n, point, ci_low, false_q1, apparatus) so the chain quotes the pre-run map."""
    rig_holder: dict[str, Rig] = {}
    calls: list[tuple[str, int]] = []  # (item id, builder calls so far at the time of the read)

    def route_for(item: BacklogItem) -> dict[str, Any]:
        calls.append((item.id, rig_holder["rig"].builder.calls))
        return DELIVER_ROUTE

    rig = _rig(
        pyrepo,
        tmp_path,
        builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED),  # forces one rework
        rework_test=lambda item, verdict, previous: STRONGER_MULTIPLY,  # a CHANGED oracle
        deliver=True,
        creds=_creds(),
        route_decision_for=route_for,
    )
    rig_holder["rig"] = rig
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.reworks == 1 and out.delivery is not None
    # exactly one read, before the first build — and NOT again for the rework's delivery
    assert calls == [("I-1", 0)] and rig.builder.calls == 2
    # the reading is on the chain, in the readiness route event, summarised
    (route,) = rig.evidence.events_for("I-1", fe.EV_ROUTE)
    assert route.payload["route"] == rd.ROUTE_BUILD
    assert route.payload["cell_route"] == {
        "route": "deliver",
        "reason": DELIVER_ROUTE["reason"],
        "reason_code": "deliver",
        "n": 12,
        "point": 1.0,
        "ci_low": 0.76,
        "false_q1": 0,
        "policy_version": "routing.v1",
        "apparatus_versions": ["2.2"],
    }
    kinds = rig.kinds("I-1")
    assert kinds.index(fe.EV_ROUTE) < kinds.index(fe.EV_RED_PROOF) < kinds.index(fe.EV_BUILD)
    # the PR body quotes that reading
    assert "route: **deliver** — n=12 point=1.000 ci_low=0.76 false_q1=0" in rig.prs[0]["body"]
    emitted = [e for e in rig.sink.events if e.action == "route.decided"]
    assert len(emitted) == 1 and emitted[0].payload["cell_route"]["n"] == 12


def test_route_read_once_is_what_gates_delivery_even_if_the_map_moves_later(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A map that would say `human` after the build cannot reach the gate: the decision the
    item carries is the one taken at readiness (and an unmeasured cell is recorded as
    ``cell_route: None``)."""
    answers = iter([DELIVER_ROUTE, HUMAN_ROUTE, HUMAN_ROUTE])
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        route_decision_for=lambda item: next(answers),
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None and len(rig.prs) == 1
    # the reverse: nothing measured at readiness → withheld, and the chain says so
    rig2 = _rig(pyrepo, tmp_path / "b", deliver=True, creds=_creds(), route_decision_for=None)
    out2 = rig2.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out2.status == fl.STATUS_ACCEPTED and out2.delivery is None
    (route,) = rig2.evidence.events_for("I-1", fe.EV_ROUTE)
    assert route.payload["cell_route"] is None


# --- a whole backlog ------------------------------------------------------------------


def test_full_loop_on_frozen_backlog(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path)
    backlog = Backlog(items=_items(), repo="pyrepo").freeze()
    loop = rig.loop()
    with pytest.raises(BacklogError):
        loop.run_backlog(Backlog(items=_items()))  # unfrozen
    with pytest.raises(BacklogError):
        loop.run_backlog(backlog, expected_hash="0" * 64)  # hash mismatch
    outcomes = loop.run_backlog(
        backlog,
        authored={"I-1": authored_multiply()},
        expected_hash=backlog.backlog_hash,
    )
    by_id = {o.item_id: o.status for o in outcomes}
    assert by_id == {
        "I-1": fl.STATUS_ACCEPTED,
        "I-2": fl.STATUS_ACCEPTED,
        "I-3": fl.STATUS_ACCEPTED,
        "I-4": fl.STATUS_NEEDS_CONTEXT,
        "I-5": fl.STATUS_ROUTED_HUMAN,
        "I-6": fl.STATUS_BLOCKED,
    }
    # dependency order: I-1 before I-2; every item attempted or explicitly routed (all-comers)
    order = [o.item_id for o in outcomes]
    assert order.index("I-1") < order.index("I-2")
    assert rig.author.calls == ["I-2", "I-3"]
    # the freeze is on the evidence ledger first, once, with the hash; the chain verifies
    evs = rig.evidence.events()
    assert (
        evs[0].kind == fe.EV_BACKLOG_FROZEN
        and evs[0].payload["backlog_hash"] == backlog.backlog_hash
    )
    assert sum(1 for e in evs if e.kind == fe.EV_BACKLOG_FROZEN) == 1
    assert rig.evidence.verify() == len(evs)
    assert rig.evidence.events_for("I-6", fe.EV_ITEM_OUTCOME)[0].payload["blocked_on"] == ["I-4"]
    # three clean factory rows, false-Q1 = 0, main untouched, no worktrees left behind
    rows = list(rig.ledger.rows())
    assert len(rows) == 3 and all(r.clean and r.process_step == PROCESS_FACTORY for r in rows)
    assert false_q1_total(rows) == 0 and rig.ledger.verify() == 3
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha
    # every build made a scratch directory and the loop cleaned it: present AND empty
    assert (tmp_path / "scratch").is_dir() and not any((tmp_path / "scratch").iterdir())
    # running again does not re-record the freeze
    loop.run_backlog(backlog, authored={"I-1": authored_multiply()})
    assert sum(1 for e in rig.evidence.events() if e.kind == fe.EV_BACKLOG_FROZEN) == 1


def test_run_backlog_works_the_latest_evolution_of_each_item(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """F32: a frozen backlog with a registered evolution — ``I-1b`` supersedes ``I-1`` —
    is worked through ``Backlog.ordered()``: the loop attempts the evolution, never the
    superseded original, the freeze it records is the FROZEN items' (the evolution is
    chained on top, and the record still verifies), and the item's outcome is the
    evolution's."""
    from dataclasses import replace as dc_replace

    rig = _rig(pyrepo, tmp_path)
    original = multiply_item()
    evolved = dc_replace(
        original, id="I-1b", title="Add multiply to calc (strengthened oracle)", supersedes="I-1"
    )
    backlog = Backlog(items=(original,), repo="pyrepo").freeze().evolve(evolved)
    assert backlog.verify() and backlog.superseded_ids() == {"I-1"}
    outcomes = rig.loop().run_backlog(
        backlog,
        authored={"I-1b": authored_multiply()},
        expected_hash=backlog.backlog_hash,
    )
    assert [(o.item_id, o.status) for o in outcomes] == [("I-1b", fl.STATUS_ACCEPTED)]
    evs = rig.evidence.events()
    assert evs[0].kind == fe.EV_BACKLOG_FROZEN and evs[0].payload["item_ids"] == ["I-1"]
    assert not rig.evidence.events_for("I-1") and rig.evidence.events_for("I-1b")
    assert rig.evidence.verify() == len(evs)


def test_a_dependency_is_resolved_through_its_evolution_before_the_block_check(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A dependant names its dependency by the REGISTERED id; when an evolution replaced
    that dependency and the evolution was not accepted, the dependant is blocked on the
    evolution's id — never built because the raw id has no outcome (verifier on
    feat/shippable, 2026-09-22: ``ordered()`` resolved the chain but the block check did
    not)."""
    from dataclasses import replace as dc_replace

    rig = _rig(pyrepo, tmp_path)
    needs_route, route = _items()[5], _items()[3]  # I-6 depends on I-4 (unsigned gap)
    route_b = dc_replace(route, id="I-4b", title="Add a health route (revised)", supersedes="I-4")
    backlog = Backlog(items=(route, needs_route), repo="pyrepo").freeze().evolve(route_b)
    assert backlog.resolve("I-4") == "I-4b" and backlog.resolve("I-6") == "I-6"
    outcomes = rig.loop().run_backlog(backlog, expected_hash=backlog.backlog_hash)
    assert [(o.item_id, o.status) for o in outcomes] == [
        ("I-4b", fl.STATUS_NEEDS_CONTEXT),
        ("I-6", fl.STATUS_BLOCKED),
    ]
    blocked = rig.evidence.events_for("I-6", fe.EV_ITEM_OUTCOME)
    assert blocked and blocked[0].payload["blocked_on"] == ["I-4b"]
    assert rig.author.calls == [], "the dependant was never sent to a builder"


def test_horizon_checkpoint_is_ledgered(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path)
    ev = rig.loop().checkpoint(
        "L1", observations=3, issues_minted=["I-7"], signed_off_by="po@example"
    )
    assert ev.kind == fe.EV_CHECKPOINT
    assert ev.payload["verification_mode"] == fe.VERIFICATION_MODES["L1"]
    with pytest.raises(ValueError):
        rig.loop().checkpoint("L4", observations=0, issues_minted=[], signed_off_by="x")
