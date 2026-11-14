"""The adapter's context-set run: one arm, every row stamped, the entry guarded (ADR-0050).

A context-set run (the ``entries`` role) is ``A0+library@ctx.<source>.<hex>``; a control run
is plain ``A0`` with ``ctx_source`` = ``control``. ``run_arm_for`` and the build closure name
the same arm; every attempt — a refusal before compose, an exception, a composed brief —
carries the task's ctx stamps, the composer's own counts winning; an entry reaches the brief
only through the arm's admission rule and the leak guard, so an entry-only brief computes the
commit's novel tokens. Inconsistent arguments are a :class:`ValueError` before any attempt.

Navigation
----------
What it is:   The tests of ``crb.builders.adapter``'s context-set arguments (ADR-0050 item 5).
What it does: Pins ``run_arm_for``'s context-set arm and its refusals; ``build_fn_for``'s
              argument checks; that every early exit of an entries run and a control run
              carries stamps ``ctx_label_violation`` accepts; that compose's counts replace
              the stamps' zeros; that a leaking or wrongly anchored entry is not delivered.
How:          A scripted ``ctxfake`` builder over the ``pyrepo`` fixture with the real
              ``PytestRunner`` and ``LocalExecutor``; stamps hand-built in ``run_stamps``'s shape.
Layer:        tests — docs/ARCHITECTURE.md#45-c4-level-3--crbbuilders
ADRs:         docs/adr/0050-context-set-arms.md, docs/adr/0026-the-context-standard.md
Works with:   src/crb/builders/adapter.py (under test), src/crb/builders/brief.py (``compose``,
              ``ContextEntry``), src/crb/core/ledger.py (``ctx_label_violation``),
              tests/fixtures/pyrepo.py (the tiny git repository the adapter builds in)
Tested by:    tests/test_adapter_ctx.py
Touch when:   never for a new repository; a ctx stamp, an early exit of the build closure, or the
              arm rule changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import (
    STOP_MAX_TURNS,
    Budget,
    BuildBrief,
    BuildOutcome,
    EscalationLadder,
    EventFn,
    Rung,
)
from crb.builders.brief import LABEL_CONTEXT_ARM, ContextEntry, S1Arm
from crb.core import context_arm as ca
from crb.core.execution import LocalExecutor
from crb.core.ledger import ctx_label_violation
from crb.core.prevention import AUTO_CONTEXT, AUTO_OFF, LearningSnapshot
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

DIGEST = "ab" * 32
MECH = f"ctx.mech.{DIGEST[:12]}"
ORACLE = f"ctx.oracle.{DIGEST[:12]}"
GAP_RULE = "anchor.v1"
#: an entry that names nothing the feat commit introduced
SAFE_TEXT = "The calculator module keeps one function per operation."
#: an entry that names the commit's answer (``subtract`` is new in the feat commit)
LEAK_TEXT = "Add a subtract function beside add."


class CtxFakeBuilder:
    """Registered as ``ctxfake``: records the brief, then gives up or raises."""

    name = "ctxfake"
    briefs: list[BuildBrief] = []  # noqa: RUF012 - reset by the autouse fixture

    def __init__(self, *, model: str, provider: str = "", behaviour: str = "noop") -> None:
        self.model = model
        self.provider = provider
        self.behaviour = behaviour

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome:
        CtxFakeBuilder.briefs.append(brief)
        if self.behaviour == "raise":
            raise RuntimeError("builder exploded")
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=False,
            stop_reason=STOP_MAX_TURNS,
            turns=budget.max_turns,
            budget=budget,
        )


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "ctxfake", CtxFakeBuilder)
    CtxFakeBuilder.briefs = []


@pytest.fixture
def harness(pyrepo: pr.PyRepo) -> dict[str, Any]:
    return {
        "runner": PytestRunner(pyrepo.config),
        "executor": LocalExecutor(),
        "config": pyrepo.config,
    }


def _ladder(behaviour: str = "noop") -> EscalationLadder:
    return EscalationLadder((Rung("ctxfake", "m0", "p", config={"behaviour": behaviour}),))


def _stamps(source: str, gap: str = "0") -> dict[str, str]:
    """One task's labels in ``crb.core.ctxset.run_stamps``'s shape."""
    out = {
        ca.LABEL_CTX_SET: DIGEST,
        ca.LABEL_CTX_SOURCE: source,
        ca.LABEL_CTX_GAP: gap,
        ca.LABEL_CTX_GAP_RULE: GAP_RULE,
    }
    if source == ca.CTX_SOURCE_CONTROL:
        return out
    out[ca.LABEL_CTX_DELIVERED] = "0"
    out[ca.LABEL_CTX_CHARS] = "0"
    if source.startswith("mech"):
        out[ca.LABEL_CTX_DRAFTER] = "drafter.v1"
    else:
        out[ca.LABEL_CTX_CEILING] = "1"
    return out


def _entry(text: str, *, source_rev: str, mechanical: bool = True) -> ContextEntry:
    return ContextEntry(
        entry_id="e1", text=text, version="v1", mechanical=mechanical, source_rev=source_rev
    )


def _attempt(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],
    *,
    context_set: str = "",
    text: str = SAFE_TEXT,
    source_rev: str | None = None,
    rung: str = "ctxfake:m0",
    behaviour: str = "noop",
    control: bool = False,
) -> Any:
    task = pyrepo.feat_task()
    parent = pyrepo.repo.parent(task.task_id)
    source = ca.CTX_SOURCE_CONTROL if control else context_set.split(".")[1]
    entries = (
        None
        if control
        else {task.task_id: _entry(text, source_rev=parent if source_rev is None else source_rev)}
    )
    fn = adapter.build_fn_for(
        _ladder(behaviour),
        budget=Budget(),
        context_set="" if control else context_set,
        ctx_entries=entries,
        ctx_stamps={task.task_id: _stamps(source)},
        **harness,
    )
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=False)
    try:
        return fn(ws, task, "blind", rung)
    finally:
        ws.remove()


# --- run_arm_for ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [MECH, ORACLE])
def test_run_arm_for_names_the_context_set_arm(name: str) -> None:
    for learning in (None, LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_OFF)):
        arm = adapter.run_arm_for(
            "blind", learning=learning, s1_author_model=None, context_set=name
        )
        assert arm == f"A0+library@{name}" and ca.ctx_set_name(arm) == name


@pytest.mark.parametrize(
    ("mode", "author", "loop", "name"),
    [
        ("sighted", None, False, MECH),
        ("blind", "t1", False, MECH),
        ("blind", None, True, MECH),
        ("blind", None, False, "ctx.mech.short"),
        ("blind", None, False, "library-v1"),
    ],
)
def test_run_arm_for_refuses_a_context_set_off_blind_a0(
    mode: str, author: str | None, loop: bool, name: str
) -> None:
    learning = LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_CONTEXT) if loop else None
    with pytest.raises(ValueError):
        adapter.run_arm_for(mode, learning=learning, s1_author_model=author, context_set=name)


# --- build_fn_for: the arguments agree ------------------------------------------------------


def _s1() -> S1Arm:
    return S1Arm(author=lambda *_a: ("t.py", ""), author_model="t1")


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"ctx_entries": {"t": _entry(SAFE_TEXT, source_rev="p")}}, "without the set's arm"),
        ({"context_set": MECH}, "per-task ctx stamps"),
        ({"context_set": MECH, "ctx_entries": {}, "ctx_stamps": {}}, "per-task ctx stamps"),
        ({"ctx_stamps": {"t": {ca.LABEL_CTX_SOURCE: "control"}}}, "without ctx_set"),
        ({"ctx_stamps": {"t": _stamps("mech")}}, "ctx_source=control"),
        (
            {"context_set": "ctx.mech.zz", "ctx_entries": {}, "ctx_stamps": {"t": _stamps("mech")}},
            "not a context-set name",
        ),
        (
            {"context_set": MECH, "ctx_entries": {}, "ctx_stamps": {"t": _stamps("mech")}},
            "cover different tasks",
        ),
        (
            {
                "context_set": MECH,
                "ctx_entries": {"t": _entry(SAFE_TEXT, source_rev="p")},
                "ctx_stamps": {"t": _stamps("oracle")},
            },
            "do not name the set",
        ),
        (
            {
                "context_set": f"ctx.mech.{'cd' * 6}",
                "ctx_entries": {"t": _entry(SAFE_TEXT, source_rev="p")},
                "ctx_stamps": {"t": _stamps("mech")},
            },
            "do not name the set",
        ),
        (
            {"ctx_stamps": {"t": _stamps("control")}, "s1": "S1"},
            "no S1 author",
        ),
        (
            {"ctx_stamps": {"t": _stamps("control")}, "learning": "on"},
            "loop off",
        ),
    ],
)
def test_build_fn_for_refuses_inconsistent_context_set_arguments(
    harness: dict[str, Any], kw: dict[str, Any], match: str
) -> None:
    if kw.get("s1") == "S1":
        kw = {**kw, "s1": _s1()}
    if kw.get("learning") == "on":
        kw = {**kw, "learning": LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_CONTEXT)}
    with pytest.raises(ValueError, match=match):
        adapter.build_fn_for(_ladder(), budget=Budget(), **kw, **harness)


def test_without_any_context_set_argument_nothing_is_stamped(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    fn = adapter.build_fn_for(_ladder(), budget=Budget(), **harness)
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=False)
    try:
        attempt = fn(ws, pyrepo.feat_task(), "blind", "ctxfake:m0")
    finally:
        ws.remove()
    assert attempt.labels[LABEL_CONTEXT_ARM] == "A0"
    assert not set(attempt.labels) & {ca.LABEL_CTX_SET, ca.LABEL_CTX_SOURCE, ca.LABEL_CTX_GAP}


#: The arm of every run without a context set, as it was before ADR-0050 (mode, loop on, S1).
_PLAIN_ARMS = {
    ("blind", False, None): "A0",
    ("blind", True, None): "A0+L",
    ("sighted", False, None): "S3",
    ("sighted", True, None): "S3+L",
    ("blind", False, "model-a"): "S1@model-a",
    ("blind", True, "model-a"): "S1@model-a+L",
}
#: The labels a plain attempt carries, as it did before ADR-0050: no ``ctx_set`` family.
_PLAIN_KEYS = {
    LABEL_CONTEXT_ARM,
    "builder_executor",
    "ctx_brief",
    "ctx_harness",
    "ctx_refused",
    "ctx_rules",
    "ctx_ticket",
}


@pytest.mark.parametrize(("key", "arm"), sorted(_PLAIN_ARMS.items(), key=str))
def test_default_off_a_run_without_a_set_keeps_its_arm(
    key: tuple[str, bool, str | None], arm: str
) -> None:
    mode, loop, s1 = key
    learning = LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_CONTEXT) if loop else None
    assert adapter.run_arm_for(mode, learning=learning, s1_author_model=s1) == arm
    assert adapter.run_arm_for(mode, learning=learning, s1_author_model=s1, context_set="") == arm


@pytest.mark.parametrize("mode", ["blind", "sighted"])
@pytest.mark.parametrize("rung", ["ctxfake:m0", "x:y"])
def test_default_off_empty_ctx_arguments_change_no_label_and_no_brief(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any], mode: str, rung: str
) -> None:
    """ADR-0050 is default-off: the worker passes ``context_set=""`` and no entries or stamps
    for a run without a set, and the attempt's labels and brief are those of a call that
    names none of the three — the label set a plain attempt carried before the change."""
    task = pyrepo.feat_task()
    got: list[tuple[dict[str, str], str]] = []
    for kw in ({}, {"context_set": "", "ctx_entries": None, "ctx_stamps": None}):
        CtxFakeBuilder.briefs = []
        fn = adapter.build_fn_for(_ladder(), budget=Budget(), **kw, **harness)  # type: ignore[arg-type]
        ws = pyrepo.trial(tmp_path / f"t{len(got)}", overlay_tests=False)
        try:
            attempt = fn(ws, task, mode, rung)
        finally:
            ws.remove()
        brief = CtxFakeBuilder.briefs[0].message if CtxFakeBuilder.briefs else ""
        got.append((dict(attempt.labels), brief))
    assert got[0] == got[1]
    labels = got[0][0]
    assert labels[LABEL_CONTEXT_ARM] == ("A0" if mode == "blind" else "S3")
    expect = _PLAIN_KEYS if rung == "ctxfake:m0" else {LABEL_CONTEXT_ARM, "builder_executor"}
    assert set(labels) == expect


# --- every row carries the stamps -----------------------------------------------------------


@pytest.mark.parametrize("control", [False, True])
def test_a_refusal_before_compose_carries_the_stamps(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any], control: bool
) -> None:
    attempt = _attempt(pyrepo, tmp_path, harness, context_set=MECH, control=control, rung="x:y")
    assert "unknown rung" in attempt.error and CtxFakeBuilder.briefs == []
    arm = attempt.labels[LABEL_CONTEXT_ARM]
    assert arm == ("A0" if control else f"A0+library@{MECH}")
    assert attempt.labels[ca.LABEL_CTX_SET] == DIGEST
    assert attempt.labels[ca.LABEL_CTX_GAP] == "0"
    assert ctx_label_violation(arm, attempt.labels) == ""
    if control:
        assert attempt.labels[ca.LABEL_CTX_SOURCE] == ca.CTX_SOURCE_CONTROL
        assert ca.LABEL_CTX_DELIVERED not in attempt.labels
    else:
        assert attempt.labels[ca.LABEL_CTX_DELIVERED] == "0"


def test_an_exception_before_compose_carries_the_stamps(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_kw: Any) -> frozenset[str]:
        raise RuntimeError("git grep fell over")

    monkeypatch.setattr(adapter, "novel_tokens", boom)
    attempt = _attempt(pyrepo, tmp_path, harness, context_set=MECH)
    assert attempt.error.startswith("RuntimeError: git grep fell over")
    arm = attempt.labels[LABEL_CONTEXT_ARM]
    assert arm == f"A0+library@{MECH}"
    assert ctx_label_violation(arm, attempt.labels) == ""


def test_a_builder_that_raises_after_compose_carries_the_composers_counts(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    attempt = _attempt(pyrepo, tmp_path, harness, context_set=MECH, behaviour="raise")
    assert attempt.error.startswith("builder raised RuntimeError")
    assert attempt.labels[ca.LABEL_CTX_DELIVERED] == "1"
    assert attempt.labels[ca.LABEL_CTX_CHARS] == str(len(SAFE_TEXT))
    assert ctx_label_violation(attempt.labels[LABEL_CONTEXT_ARM], attempt.labels) == ""


@pytest.mark.parametrize("control", [False, True])
def test_a_control_and_an_entries_run_stamp_the_same_gap_and_set(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any], control: bool
) -> None:
    attempt = _attempt(pyrepo, tmp_path, harness, context_set=MECH, control=control)
    arm = attempt.labels[LABEL_CONTEXT_ARM]
    assert ctx_label_violation(arm, attempt.labels) == ""
    assert attempt.labels[ca.LABEL_CTX_SET] == DIGEST
    assert attempt.labels[ca.LABEL_CTX_GAP_RULE] == GAP_RULE
    (brief,) = CtxFakeBuilder.briefs
    assert brief.blind
    assert (SAFE_TEXT in brief.spec_facts) is not control


# --- the entry is guarded -------------------------------------------------------------------


def test_a_delivered_entry_reaches_the_brief_and_is_counted(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    attempt = _attempt(pyrepo, tmp_path, harness, context_set=MECH)
    (brief,) = CtxFakeBuilder.briefs
    assert brief.spec_facts == (SAFE_TEXT,)
    assert attempt.labels[ca.LABEL_CTX_DELIVERED] == "1"
    assert attempt.labels[ca.LABEL_CTX_CHARS] == str(len(SAFE_TEXT))
    assert attempt.labels[ca.LABEL_CTX_DRAFTER] == "drafter.v1"


@pytest.mark.parametrize("name", [MECH, ORACLE])
def test_the_leak_guard_runs_on_an_entry_only_brief(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any], name: str
) -> None:
    """No learned line, no fact: the entry alone still makes the closure compute the commit's
    novel tokens, so an entry naming the answer is refused on a hindsight arm too."""
    attempt = _attempt(pyrepo, tmp_path, harness, context_set=name, text=LEAK_TEXT)
    (brief,) = CtxFakeBuilder.briefs
    assert LEAK_TEXT not in brief.spec_facts and LEAK_TEXT not in brief.task_text()
    assert attempt.labels[ca.LABEL_CTX_DELIVERED] == "0"
    assert attempt.labels[ca.LABEL_CTX_CHARS] == "0"
    assert int(attempt.labels[ca.LABEL_CTX_REFUSED]) >= 1
    assert ctx_label_violation(attempt.labels[LABEL_CONTEXT_ARM], attempt.labels) == ""


def test_a_mechanical_entry_not_drafted_at_the_parent_is_refused(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    attempt = _attempt(pyrepo, tmp_path, harness, context_set=MECH, source_rev="0" * 40)
    (brief,) = CtxFakeBuilder.briefs
    assert brief.spec_facts == ()
    assert attempt.labels[ca.LABEL_CTX_DELIVERED] == "0"
    assert attempt.labels[ca.LABEL_CTX_REFUSED] == "1"


def test_a_context_set_run_never_builds_sighted(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    task = pyrepo.feat_task()
    fn = adapter.build_fn_for(
        _ladder(),
        budget=Budget(),
        ctx_stamps={task.task_id: _stamps(ca.CTX_SOURCE_CONTROL)},
        **harness,
    )
    ws = pyrepo.trial(tmp_path / "t")
    try:
        with pytest.raises(ValueError, match="blind"):
            fn(ws, task, "sighted", "ctxfake:m0")
    finally:
        ws.remove()
    assert CtxFakeBuilder.briefs == []
