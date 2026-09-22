"""crb.factory.loop — one item end to end, and a frozen backlog under the all-comers rule.

Navigation
----------
What it is:   The factory loop's test suite — one item end to end, and a frozen backlog under
              the all-comers rule.
What it does: Pins that a spec refuses a test author that is also a rung, that a single item is
              accepted with delivery off by default, that an unsigned structural gap is refused
              and recorded, that an operator item is routed human not built, the test-first route
              through the author rung, that no oracle means no build, that a green authored test
              is not RED, that a not-clean build stops before delivery and review, that delivery
              on fails closed without credentials and otherwise opens a branch + PR then reviews,
              that accept-with-edit forces rework (RED → build → grade → a re-delivery that
              UPDATES the first pull request → fresh verdict; a failed rework comment is a
              warning on the record, never a stop) until the budget is exhausted, that a
              ``weak_oracle`` verdict never rebuilds against an unchanged oracle (no test
              author, or one that returns the same bytes → ``oracle_needs_strengthening``,
              routed human with a reason whose prefix survives a 2000-char finding;
              DL-045 rule 3), that
              the route gate reads the capability map ONCE per item at readiness — before any
              build — and the PR body quotes that reading (DL-045), the full loop on a frozen
              backlog, and the ledgered horizon checkpoint.
How:          ``Rig`` wires ``MultiBuilder`` (edit picked from the brief's subject; can misbehave
              once), ``FakeTestAuthor``, a ``MemorySink`` emitter, static credentials and
              recording push / PR / comment seams over ``pyrepo``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/factory/loop.py (under test), src/crb/factory/readiness.py (the DoR
              gate), src/crb/factory/build.py, src/crb/factory/delivery.py and
              src/crb/factory/review.py (the steps it sequences), src/crb/factory/evidence.py
              (the factory evidence chain), tests/test_factory_build.py (the shared harness)
Tested by:    tests/test_factory_loop.py
Touch when:   a step is added to the loop (a stop-before case and an end-to-end case); the
              rework budget rule changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from crb.builders.base import BuildBrief, BuildOutcome, Rung
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
from crb.factory.delivery import DeliveryError, GitCredentials, StaticProvider
from crb.factory.testfirst import AuthoredTest, SameIdentityError
from crb.observability.events import Emitter, MemorySink, StepStatus
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
    assert rig.kinds("I-1") == [
        fe.EV_READINESS,
        fe.EV_ROUTE,
        fe.EV_RED_PROOF,
        fe.EV_BUILD,
        fe.EV_DELIVERY_REFUSED,
        fe.EV_VERDICT,
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
    assert out.status == fl.STATUS_NOT_READY and out.proof is None and not out.builds
    assert out.readiness is not None and {g.slot for g in out.readiness.blocking_gaps} == {
        "request_shape",
        "response_shape",
        "error_contract",
    }
    assert rig.kinds("I-4") == [fe.EV_READINESS, fe.EV_ROUTE, fe.EV_ITEM_OUTCOME]
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
    out = rig.loop().run_item(multiply_item())
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
    assert not rig.pushes and not rig.prs and not out.verdicts
    assert rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha


def test_delivery_on_opens_branch_and_pr_then_reviews(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    creds = StaticProvider(
        GitCredentials(remote="https://github.com/acme/calc.git", token="ghp_" + "b" * 36)
    )
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=creds, target_default_branch="main")
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    assert out.delivery.branch == "crb/I-1-add-multiply-to-calc" and out.delivery.base == "main"
    assert rig.pushes == [
        {
            "branch": out.delivery.branch,
            "refspec": f"{out.delivery.branch}:{out.delivery.branch}",
            "expected": None,
        }
    ]
    assert out.final_verdict is not None and out.final_verdict.pr_ref == out.delivery.pr_url
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha  # never main
    kinds = rig.kinds("I-1")
    assert fe.EV_DELIVERY in kinds and kinds.index(fe.EV_DELIVERY) < kinds.index(fe.EV_VERDICT)


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


def test_route_gate_override_by_an_approver_is_itself_on_the_record(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        route_decision_for=lambda item: HUMAN_ROUTE,
        deliver_override_by="approver:ada",
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    assert len(rig.pushes) == 1 and len(rig.prs) == 1
    routes = [e.payload for e in rig.evidence.events_for("I-1", fe.EV_ROUTE)]
    override = [r for r in routes if r.get("override_by")]
    assert len(override) == 1
    assert override[0]["route"] == "deliver" and override[0]["measured_route"] == "human"
    assert (
        override[0]["override_by"] == "approver:ada" and override[0]["reason_code"] == "oracle_weak"
    )
    assert "route gate overridden by approver:ada" in override[0]["reason"]
    kinds = rig.kinds("I-1")
    assert kinds.index(fe.EV_ROUTE) < kinds.index(fe.EV_DELIVERY)


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
    # the delivery branch was re-pointed by the rework: two pushes, ONE pull request — the
    # second push leases against the commit the first delivery pushed and updates the PR
    # the first delivery opened (B-1b finding 1, DL-045)
    assert [p["branch"] for p in rig.pushes] == ["crb/I-1-add-multiply-to-calc"] * 2
    opened = rig.evidence.events_for("I-1", fe.EV_DELIVERY)
    assert len(opened) == 1 and len(rig.prs) == 1
    first_commit = str(opened[0].payload["commit_sha"])
    assert [p["expected"] for p in rig.pushes] == [None, first_commit]
    assert out.delivery is not None and out.delivery.updated
    assert out.delivery.pr_number == 1 and out.delivery.pr_url == opened[0].payload["pr_url"]
    assert out.delivery.previous_commit_sha == first_commit != out.delivery.commit_sha
    assert out.final_verdict is not None and out.final_verdict.pr_ref == out.delivery.pr_url
    updated = rig.evidence.events_for("I-1", fe.EV_DELIVERY_UPDATED)
    assert len(updated) == 1
    up = updated[0].payload
    assert up["rework"] == 1 and up["after_verdict"] == rv.VERDICT_ACCEPT_WITH_EDIT
    assert up["previous_commit_sha"] == first_commit and up["commit_sha"] == out.delivery.commit_sha
    assert up["pr_url"] == out.delivery.pr_url and up["updated"] is True
    (comment,) = rig.comments
    assert comment["pr_number"] == 1 and "Rework 1" in comment["body"]
    assert first_commit in comment["body"] and out.delivery.commit_sha in comment["body"]
    assert up["body_sha256"] and out.delivery.body_sha256 == up["body_sha256"]
    assert [e.action for e in rig.sink.events if e.action.startswith("delivery.")] == [
        "delivery.opened",
        "delivery.updated",
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
    # verdict → edit permitted → RED proof → build → re-delivery → fresh verdict, in that order
    v1 = kinds.index(fe.EV_VERDICT)
    assert kinds[v1 + 1] == fe.EV_EDIT
    assert kinds[v1 + 2] == fe.EV_RED_PROOF and fe.EV_BUILD in kinds[v1 + 2 :]
    assert kinds[v1 + 2 :].index(fe.EV_BUILD) < kinds[v1 + 2 :].index(fe.EV_DELIVERY_UPDATED)
    assert kinds.count(fe.EV_VERDICT) == 2 and kinds[-2] == fe.EV_VERDICT
    assert rig.evidence.verify() == len(kinds)
    rows = list(rig.ledger.rows())
    assert len(rows) == 2 and all(r.process_step == PROCESS_FACTORY for r in rows)
    assert [r.trial for r in rows] == ["r1", "w1r1"] and false_q1_total(rows) == 0


def test_rework_whose_pull_request_comment_fails_is_still_updated_and_reviewed(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The rework comment is posted AFTER the lease push has moved the remote branch. When
    it fails (a rate limit, a 5xx, a timeout) the branch and the pull request already carry
    the rework: the loop must record `delivery.updated` (with the failure as
    ``comment_error``), warn, and REVIEW the moved branch — never end the item
    `delivery_failed` with a `delivery.refused` that contradicts the remote."""
    stronger = AuthoredTest(
        "tests/test_multiply.py",
        TEST_MULTIPLY_SRC + "\n\ndef test_multiply_other():\n    assert multiply(5, 6) == 30\n",
        OPERATOR,
    )
    comments: list[dict[str, Any]] = []

    def failing_comment(**kw: Any) -> None:
        comments.append(kw)
        raise DeliveryError("GitHub comments API returned 403: rate limit exceeded")

    creds = StaticProvider(
        GitCredentials(remote="https://github.com/acme/calc.git", token="x" * 20)
    )
    rig = _rig(
        pyrepo,
        tmp_path,
        builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED),
        rework_test=lambda item, verdict, previous: stronger,
        deliver=True,
        creds=creds,
        comment_pr_fn=failing_comment,
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    # the item ran to its fresh verdict; the rework's build is the one reviewed
    assert out.status == fl.STATUS_ACCEPTED and out.reworks == 1 and out.error == ""
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT, rv.VERDICT_ACCEPT]
    opened = rig.evidence.events_for("I-1", fe.EV_DELIVERY)
    first_commit = str(opened[0].payload["commit_sha"])
    assert [p["expected"] for p in rig.pushes] == [None, first_commit]
    assert out.delivery is not None and out.delivery.updated
    assert out.delivery.commit_sha != first_commit
    assert out.delivery.commit_sha == pyrepo.repo.rev_parse("crb/I-1-add-multiply-to-calc")
    # the chain agrees with the remote: updated, with the comment failure on the event
    assert not rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    (updated,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_UPDATED)
    assert updated.payload["commit_sha"] == out.delivery.commit_sha
    assert updated.payload["body_sha256"] == "" and out.delivery.body_sha256 == ""
    assert updated.payload["comment_error"] == out.delivery.comment_error
    assert out.delivery.comment_error.startswith("DeliveryError: GitHub comments API returned 403")
    assert len(comments) == 1 and comments[0]["pr_number"] == 1
    # the step events: the update is recorded, the failed comment is a warning, not a stop
    steps = [e for e in rig.sink.events if e.action.startswith("delivery.")]
    assert [e.action for e in steps] == [
        "delivery.opened",
        "delivery.updated",
        "delivery.comment_failed",
    ]
    assert steps[1].status == StepStatus.OK and steps[2].status == StepStatus.ERROR
    assert steps[2].error_message == out.delivery.comment_error
    assert steps[2].payload["pr"] == out.delivery.pr_url
    kinds = rig.kinds("I-1")
    assert kinds.count(fe.EV_VERDICT) == 2 and kinds[-2] == fe.EV_VERDICT
    assert kinds.index(fe.EV_DELIVERY_UPDATED) < len(kinds) - 2  # the fresh verdict follows it
    assert rig.evidence.verify() == len(kinds)


def _assert_stopped_for_a_stronger_oracle(rig: Rig, out: fl.ItemOutcome) -> None:
    """DL-045 rule 3, both halves: the item ends ``oracle_needs_strengthening`` with ONE
    build, ONE push, ONE pull request and ONE verdict; the chain routes it human with the
    reviewer's finding in the reason; the trace carries ``rework.refused``."""
    assert out.status == fl.STATUS_ORACLE_NEEDS_STRENGTHENING and not out.accepted
    assert [v.verdict for v in out.verdicts] == [rv.VERDICT_ACCEPT_WITH_EDIT]
    assert rig.builder.calls == 1 and [b["trial"] for b in out.builds] == ["r1"]
    assert len(rig.pushes) == 1 and len(rig.prs) == 1 and rig.comments == []
    assert out.delivery is not None and not out.delivery.updated
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
    assert [e.action for e in rig.sink.events if e.action.startswith("delivery.")] == [
        "delivery.opened"
    ]
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
    # the branch still carries the one delivered build, not a rework
    assert out.delivery is not None
    assert out.delivery.commit_sha == pyrepo.repo.rev_parse("crb/I-1-add-multiply-to-calc")


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
    same oracle, a fresh RED proof, a second build, the pull request updated."""

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
    assert rig.builder.calls == 2 and len(rig.pushes) == 2 and len(rig.prs) == 1
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
        "I-4": fl.STATUS_NOT_READY,
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
        ("I-4b", fl.STATUS_NOT_READY),
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
