"""The builder→orchestrator adapter: label parsing, brief construction (no src_files,
blind carries no tests), every failure a recorded non-pass, and an end-to-end
``crb.core.run.run`` with a fake builder that the grader marks clean."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import (
    STOP_DONE,
    STOP_MAX_TURNS,
    STOP_MODEL_ERROR,
    Budget,
    BuildBrief,
    BuildOutcome,
    EscalationLadder,
    EventFn,
    Rung,
)
from crb.core.execution import LocalExecutor
from crb.core.ledger import JsonlLedger, verify_chain
from crb.core.run import BuildAttempt, RunSpec, run
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

# --- a scripted builder ---------------------------------------------------------------------


class FakeBuilder:
    """Registered as ``fake``; ``behaviour`` picks what it does with the worktree."""

    name = "fake"
    briefs: ClassVar[list[BuildBrief]] = []
    instances: ClassVar[list[FakeBuilder]] = []

    def __init__(
        self, *, model: str, provider: str = "", behaviour: str = "gold", **cfg: Any
    ) -> None:
        self.model = model
        self.provider = provider
        self.behaviour = behaviour
        self.cfg = cfg
        FakeBuilder.instances.append(self)

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
        FakeBuilder.briefs.append(brief)
        if on_event is not None:
            on_event("build.attempt", {"attempt": 1})
        base = {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "mode": brief.mode,
        }
        if self.behaviour == "gold":
            pr.apply_gold(workspace)
            return BuildOutcome(
                **base,
                done=True,
                stop_reason=STOP_DONE,
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.01,
                budget=budget,
                transcript=({"kind": "attempt", "attempt": 1},),
            )
        if self.behaviour == "noop":
            return BuildOutcome(
                **base,
                done=False,
                stop_reason=STOP_MAX_TURNS,
                turns=budget.max_turns,
                budget=budget,
            )
        if self.behaviour == "model_error":
            return BuildOutcome(
                **base,
                done=False,
                stop_reason=STOP_MODEL_ERROR,
                errors=("model_error: 401 api_key=sk-live-abcdefghijklmnopqrstuvwxyz",),
            )
        if self.behaviour == "archaeology":
            pr.apply_gold(workspace)
            return BuildOutcome(
                **base,
                done=True,
                stop_reason=STOP_DONE,
                errors=("archaeology: 'git show' is not allowed",),
            )
        if self.behaviour == "raise":
            raise RuntimeError("builder exploded")
        raise AssertionError(self.behaviour)


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.instances = []


@pytest.fixture
def harness(pyrepo: pr.PyRepo) -> dict[str, Any]:
    return {
        "runner": PytestRunner(pyrepo.config),
        "executor": LocalExecutor(),
        "config": pyrepo.config,
    }


# --- labels ⇄ ladder ------------------------------------------------------------------------


def test_parse_rung_label_accepts_both_spellings() -> None:
    assert adapter.parse_rung_label("editblock:gpt-oss-120b") == Rung("editblock", "gpt-oss-120b")
    assert adapter.parse_rung_label("editblock:gpt-oss-120b:cerebras") == Rung(
        "editblock", "gpt-oss-120b", "cerebras"
    )
    assert adapter.parse_rung_label("editblock:gpt-oss-120b@cerebras") == Rung(
        "editblock", "gpt-oss-120b", "cerebras"
    )
    assert adapter.parse_rung_label(" claude_code : claude-opus-5 ") == Rung(
        "claude_code", "claude-opus-5"
    )
    # a model id with ':' needs '@' for the provider
    assert adapter.parse_rung_label("openai_agent:azure:gpt-4o@azure") == Rung(
        "openai_agent", "azure:gpt-4o", "azure"
    )
    assert (
        adapter.parse_rung_label("editblock:m", default_provider="cerebras").provider == "cerebras"
    )
    assert (
        adapter.parse_rung_label("editblock:m:local", default_provider="cerebras").provider
        == "local"
    )
    with pytest.raises(ValueError):
        adapter.parse_rung_label("editblock")
    with pytest.raises(ValueError):
        adapter.parse_rung_label("editblock:")


def test_ladder_from_spec_and_labels_round_trip() -> None:
    ladder = adapter.ladder_from_spec(
        ["editblock:m1@cerebras", "", "claude_code:opus"], default_provider="anthropic"
    )
    assert [r.provider for r in ladder] == ["cerebras", "anthropic"]
    assert adapter.ladder_labels(ladder) == ("editblock:m1", "claude_code:opus")
    with pytest.raises(ValueError):
        adapter.ladder_from_spec([])
    with pytest.raises(ValueError):
        adapter.ladder_from_spec(["", "   "])


def test_ladder_labels_disambiguate_duplicates() -> None:
    ladder = EscalationLadder(
        (Rung("fake", "m", "a"), Rung("fake", "m", "b"), Rung("fake", "m", "b"), Rung("fake", "m"))
    )
    labels = adapter.ladder_labels(ladder)
    assert labels == ("fake:m", "fake:m@b", "fake:m#2", "fake:m#3")
    assert len(set(labels)) == 4
    index = adapter.rung_index(ladder)
    assert index["fake:m"] is ladder.rungs[0]
    assert index["fake:m@a"] is ladder.rungs[0] and index["fake:m:a"] is ladder.rungs[0]
    assert index["fake:m@b"] is ladder.rungs[1]
    assert index["fake:m#2"] is ladder.rungs[2] and index["fake:m#3"] is ladder.rungs[3]


# --- attempt mapping ------------------------------------------------------------------------


def _outcome(**kw: Any) -> BuildOutcome:
    base: dict[str, Any] = {"builder": "fake", "model": "m", "provider": "p", "mode": "sighted"}
    base.update(kw)
    return BuildOutcome(**base)


def test_attempt_error_rules() -> None:
    assert adapter.attempt_error(_outcome(stop_reason=STOP_DONE)) == ""
    assert (
        adapter.attempt_error(_outcome(stop_reason=STOP_MAX_TURNS)) == ""
    )  # a budget cap is honest
    err = adapter.attempt_error(
        _outcome(stop_reason=STOP_MODEL_ERROR, errors=("model_error: 500",))
    )
    assert err.startswith("model_error: ") and "500" in err
    assert (
        adapter.attempt_error(_outcome(stop_reason=STOP_MODEL_ERROR))
        == "model_error: builder reported a model error"
    )
    v = adapter.attempt_error(_outcome(stop_reason=STOP_DONE, errors=("network: curl", "other")))
    assert v == "protocol violation: network: curl"
    # a violation dominates even a model error
    both = adapter.attempt_error(
        _outcome(stop_reason=STOP_MODEL_ERROR, errors=("tamper: tests/x.py",))
    )
    assert both.startswith("protocol violation")


def test_attempt_error_caps_the_detail_never_the_prefix() -> None:
    """A long docker refusal capped tail-first lost its ``protocol violation:`` head and
    the ledger read the row as ``harness`` (mesh-client, 2026-09-15)."""
    long = "network: docker " + "x" * 3000  # over BuildOutcome's own 2000-char cap too
    out = _outcome(stop_reason=STOP_DONE, errors=(long,))
    assert out.violated  # the outcome keeps the head of each error
    v = adapter.attempt_error(out)
    assert v.startswith("protocol violation: network: docker x") and v.endswith(" …")
    assert len(v) <= 500
    m = adapter.attempt_error(
        _outcome(stop_reason=STOP_MODEL_ERROR, errors=("model_error: " + "y" * 2000,))
    )
    assert (
        m.startswith("model_error: yyy") and len(m) <= 500 and "model_error: model_error" not in m
    )


# --- build_fn: briefs -----------------------------------------------------------------------


def _ladder(*behaviours: str) -> EscalationLadder:
    return EscalationLadder(
        tuple(Rung("fake", f"m{i}", "p", config={"behaviour": b}) for i, b in enumerate(behaviours))
    )


def test_sighted_brief_carries_tests_and_command_but_never_src_files(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    task = pyrepo.feat_task()
    fn = adapter.build_fn_for(
        _ladder("noop"),
        budget=Budget(),
        message_for=lambda t: "feat: add subtract\n\nLong body.",
        **harness,
    )
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, task, "sighted", "fake:m0")
    finally:
        ws.remove()
    assert attempt.error == "" and attempt.builder.name == "fake"
    (brief,) = FakeBuilder.briefs
    assert brief.mode == "sighted"
    assert brief.test_files == (pr.TEST_SUBTRACT,) and brief.target_tests == (pr.TEST_SUBTRACT,)
    assert "pytest" in brief.test_command and pr.TEST_SUBTRACT in brief.test_command
    assert brief.message == "feat: add subtract\n\nLong body."
    assert brief.config is pyrepo.config
    assert "src_files" not in brief.to_dict()
    assert pr.SRC not in brief.task_text()


def test_blind_brief_carries_no_tests_no_command(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    task = pyrepo.feat_task()
    fn = adapter.build_fn_for(_ladder("noop"), budget=Budget(), **harness)
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=False)
    try:
        fn(ws, task, "blind", "fake:m0")
    finally:
        ws.remove()
    (brief,) = FakeBuilder.briefs
    assert (
        brief.blind
        and brief.test_files == ()
        and brief.target_tests == ()
        and brief.test_command == ""
    )
    assert brief.message == task.subject  # default message: the subject
    assert pr.TEST_SUBTRACT not in brief.task_text()


def test_message_for_failure_falls_back_to_subject(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    def boom(_t: TaskSpec) -> str:
        raise RuntimeError("git down")

    fn = adapter.build_fn_for(_ladder("noop"), budget=Budget(), message_for=boom, **harness)
    ws = pyrepo.trial(tmp_path / "t")
    try:
        fn(ws, pyrepo.feat_task(), "sighted", "fake:m0")
    finally:
        ws.remove()
    assert FakeBuilder.briefs[0].message == "feat: add subtract"


# --- build_fn: failures are recorded, never raised ----------------------------------------


def test_unknown_rung_is_a_recorded_error(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    fn = adapter.build_fn_for(_ladder("gold"), budget=Budget(), **harness)
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "fake:zzz")
        assert ws.touched_files() == [pr.TEST_SUBTRACT]  # nothing was built
    finally:
        ws.remove()
    assert "unknown rung" in attempt.error and attempt.builder.name == "fake:zzz"
    assert FakeBuilder.briefs == []


def test_unregistered_builder_is_a_recorded_error(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    ladder = EscalationLadder((Rung("no-such-builder", "m"),))
    fn = adapter.build_fn_for(ladder, budget=Budget(), **harness)
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "no-such-builder:m")
    finally:
        ws.remove()
    assert attempt.error.startswith("builder unavailable: ValueError")


def test_builder_exception_is_a_recorded_error(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    fn = adapter.build_fn_for(_ladder("raise"), budget=Budget(), **harness)
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "fake:m0")
    finally:
        ws.remove()
    assert attempt.error == "builder raised RuntimeError: builder exploded"
    assert attempt.builder.name == "fake" and attempt.builder.model == "m0"
    assert attempt.builder.budget == Budget().to_dict()


def test_model_error_and_violation_are_errors_and_redacted(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    fn = adapter.build_fn_for(_ladder("model_error", "archaeology"), budget=Budget(), **harness)
    task = pyrepo.feat_task()
    ws = pyrepo.trial(tmp_path / "t1")
    try:
        a1 = fn(ws, task, "sighted", "fake:m0")
    finally:
        ws.remove()
    assert (
        a1.error.startswith("model_error:")
        and "sk-live" not in a1.error
        and "[REDACTED" in a1.error
    )
    ws = pyrepo.trial(tmp_path / "t2")
    try:
        a2 = fn(ws, task, "sighted", "fake:m1")
    finally:
        ws.remove()
    assert a2.error == "protocol violation: archaeology: 'git show' is not allowed"


# --- build_fn: budgets, events, transcripts, caching ------------------------------------


def test_rung_budget_override_and_builder_events(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    ladder = EscalationLadder(
        (Rung("fake", "m", "p", config={"behaviour": "noop", "max_turns": 3, "junk": 1}),)
    )
    seen: list[tuple[str, dict[str, Any]]] = []
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(max_turns=25),
        on_event=lambda a, p: seen.append((a, dict(p))),
        **harness,
    )
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "fake:m")
    finally:
        ws.remove()
    assert attempt.builder.turns == 3 and attempt.builder.budget["max_turns"] == 3
    assert seen == [("builder.build.attempt", {"attempt": 1})]
    # rung config (minus budget keys) reached the constructor; the instance is cached
    (inst,) = FakeBuilder.instances
    assert inst.behaviour == "noop" and inst.cfg == {"junk": 1}
    ws = pyrepo.trial(tmp_path / "t2")
    try:
        fn(ws, pyrepo.feat_task(), "sighted", "fake:m")
    finally:
        ws.remove()
    assert len(FakeBuilder.instances) == 1


def test_builder_overrides_reach_every_builder(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    fn = adapter.build_fn_for(
        _ladder("gold"),
        budget=Budget(),
        builder_overrides={"behaviour": "noop", "extra": 2},
        **harness,
    )
    ws = pyrepo.trial(tmp_path / "t")
    try:
        fn(ws, pyrepo.feat_task(), "sighted", "fake:m0")
    finally:
        ws.remove()
    (inst,) = FakeBuilder.instances
    assert inst.behaviour == "noop" and inst.cfg == {"extra": 2}


def test_transcript_written_to_file_never_inlined(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    tdir = tmp_path / "transcripts"
    fn = adapter.build_fn_for(_ladder("gold"), budget=Budget(), transcript_dir=tdir, **harness)
    ws = pyrepo.trial(tmp_path / "t")
    try:
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "fake:m0")
    finally:
        ws.remove()
    assert attempt.transcript_ref and attempt.builder.transcript_ref == attempt.transcript_ref
    body = json.loads(Path(attempt.transcript_ref).read_text(encoding="utf-8"))
    assert body["outcome"]["transcript"] == [{"kind": "attempt", "attempt": 1}]
    assert body["task_id"] == pyrepo.feat_sha
    # no transcript, no ref
    fn2 = adapter.build_fn_for(_ladder("noop"), budget=Budget(), transcript_dir=tdir, **harness)
    ws = pyrepo.trial(tmp_path / "t2")
    try:
        assert fn2(ws, pyrepo.feat_task(), "sighted", "fake:m0").transcript_ref == ""
    finally:
        ws.remove()


def test_sighted_test_command_is_best_effort(harness: dict[str, Any], tmp_path: Path) -> None:
    cmd = adapter.sighted_test_command(
        harness["runner"], harness["executor"], tmp_path, ("tests/test_x.py",)
    )
    assert "-m pytest" in cmd and cmd.endswith("tests/test_x.py")

    class Broken(PytestRunner):
        def command(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("no")

    assert (
        adapter.sighted_test_command(
            Broken(harness["config"]), harness["executor"], tmp_path, ("t",)
        )
        == ""
    )


def test_as_run_ledger_is_a_typed_passthrough(tmp_path: Path) -> None:
    class Duck:
        def __init__(self) -> None:
            self.rows: list[Any] = []

        def append(self, row: Any) -> Any:
            self.rows.append(row)
            return row

    duck = Duck()
    assert adapter.as_run_ledger(duck) is duck  # type: ignore[comparison-overlap]


# --- end to end through the core orchestrator --------------------------------------------


def test_run_climbs_ladder_and_grades_clean(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    """Rung 1 does nothing (RED, not clean) → rung 2 applies gold → clean; two chained rows."""
    ladder = _ladder("noop", "gold")
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-adapter",
        config=pyrepo.config,
        runner=harness["runner"],
        executor=harness["executor"],
        scratch=tmp_path / "scratch",
        ledger=ledger,
        evidence_dir=tmp_path / "evidence",
        ladder=adapter.ladder_labels(ladder),
    )
    events: list[tuple[str, dict[str, Any]]] = []
    fn = adapter.build_fn_for(
        ladder, budget=Budget(), on_event=lambda a, p: events.append((a, dict(p))), **harness
    )
    summary = run(
        spec,
        pyrepo.repo,
        [pyrepo.feat_task()],
        fn,
        on_event=lambda a, p: events.append((a, dict(p))),
    )
    assert (summary.tasks, summary.clean, summary.rows, summary.first_pass_clean) == (1, 1, 2, 0)
    rows = list(ledger.rows())
    assert verify_chain(rows) == 2
    assert [(r.trial, r.model, r.clean) for r in rows] == [("r1", "m0", False), ("r2", "m1", True)]
    assert rows[1].evidence_pack_hash and rows[1].cost_usd == 0.01 and rows[1].error == ""
    assert [b.mode for b in FakeBuilder.briefs] == ["sighted", "sighted"]
    actions = [a for a, _ in events]
    assert actions.count("builder.build.attempt") == 2
    assert "ledger.append" in actions


def test_blind_run_end_to_end(pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]) -> None:
    ladder = _ladder("gold")
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-blind",
        config=pyrepo.config,
        runner=harness["runner"],
        executor=harness["executor"],
        scratch=tmp_path / "scratch",
        ledger=ledger,
        evidence_dir=tmp_path / "evidence",
        mode="blind",
        ladder=adapter.ladder_labels(ladder),
    )
    fn = adapter.build_fn_for(ladder, budget=Budget(), **harness)
    summary = run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    assert summary.clean == 1 and summary.first_pass_clean == 1
    (row,) = ledger.rows()
    assert row.mode == "blind" and row.clean
    (brief,) = FakeBuilder.briefs
    assert brief.blind and brief.test_files == ()


def test_error_attempt_row_is_never_clean(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    """A protocol violation landed the gold patch; the adapter discards it before
    grading, so the row is RED with the violation recorded — never clean, and the
    run does not abort on a clean-with-error row."""
    ladder = _ladder("archaeology")
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-viol",
        config=pyrepo.config,
        runner=harness["runner"],
        executor=harness["executor"],
        scratch=tmp_path / "scratch",
        ledger=ledger,
        evidence_dir=tmp_path / "evidence",
        ladder=adapter.ladder_labels(ladder),
    )
    events: list[tuple[str, dict[str, Any]]] = []
    fn = adapter.build_fn_for(
        ladder, budget=Budget(), on_event=lambda a, p: events.append((a, dict(p))), **harness
    )
    summary = run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    (row,) = ledger.rows()
    assert row.tests_unmodified is True and row.target_green is False
    assert row.clean is False and row.error.startswith("protocol violation")
    assert summary.clean == 0 and summary.errors == 1
    discard = [p for a, p in events if a == "builder.discard"]
    assert discard == [{"files": [pr.SRC], "error": row.error}]


def test_discard_source_edits_keeps_tests_and_removes_new_files(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    ws = pyrepo.trial(tmp_path / "t")
    try:
        pr.apply_gold(ws)  # tracked source edit
        pr.write_files(ws, [("src/calc/new_module.py", "X = 1\n")])  # untracked source
        pr.apply_test_only(ws)  # a new test file: NOT ours to discard
        dropped = adapter.discard_source_edits(ws, pyrepo.config, [pr.TEST_SUBTRACT])
        assert sorted(dropped) == [pr.SRC, "src/calc/new_module.py"]
        assert ws.touched_files() == sorted([pr.TEST_SUBTRACT, "tests/test_extra.py"])
        assert ws.read(pr.SRC) == pr.SRC_INITIAL
        assert not ws.exists("src/calc/new_module.py")
        # idempotent
        assert adapter.discard_source_edits(ws, pyrepo.config, [pr.TEST_SUBTRACT]) == []
    finally:
        ws.remove()


def test_model_error_after_a_correct_patch_is_error_not_clean(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any]
) -> None:
    """The adapter's discard makes 'clean grade + error' impossible by construction."""

    class LandsThenErrors(FakeBuilder):
        def build(
            self, workspace: Workspace, brief: BuildBrief, budget: Budget, **kw: Any
        ) -> BuildOutcome:
            pr.apply_gold(workspace)
            return BuildOutcome(
                builder="fake",
                model=self.model,
                provider="p",
                mode=brief.mode,
                stop_reason=STOP_MODEL_ERROR,
                errors=("model_error: 502",),
            )

    ladder = EscalationLadder((Rung("fake", "m"),))
    fn = adapter.build_fn_for(ladder, budget=Budget(), builder_overrides={}, **harness)
    ws = pyrepo.trial(tmp_path / "t")
    try:
        FakeBuilder.instances.clear()
        import crb.builders as b

        b._REGISTRY["fake"] = LandsThenErrors
        attempt = fn(ws, pyrepo.feat_task(), "sighted", "fake:m")
        assert attempt.error.startswith("model_error")
        assert ws.read(pr.SRC) == pr.SRC_INITIAL  # the patch is gone before grading
    finally:
        ws.remove()


def test_build_attempt_shape() -> None:
    a = BuildAttempt(adapter._failed_attempt("x:y", "blind", "why").builder, error="why")
    assert a.builder.name == "x:y" and a.builder.mode == "blind" and a.error == "why"
