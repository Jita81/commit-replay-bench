"""The builder→orchestrator adapter: label parsing, brief construction (no src_files,
blind carries no tests), every failure a recorded non-pass, and an end-to-end
``crb.core.run.run`` with a fake builder that the grader marks clean.

Navigation
----------
What it is:   The builder→orchestrator adapter's test suite — rung labels, brief construction,
              every failure a recorded non-pass, and ``crb.core.run.run`` end to end with a fake
              builder.
What it does: Pins that a sighted brief carries the tests and the test command but never
              ``src_files`` and a blind brief carries no tests and no command; that an unknown
              rung, an unregistered builder, a builder exception, a model error or a protocol
              violation each become a recorded error row (redacted) — and that a violation which
              landed the gold patch is discarded before grading, so "clean + error" is impossible
              by construction; that ``run_arm_for`` is the arm the closure stamps on each exit
              (refusal, composed brief, S1 authoring failure) in both modes, loop on and off,
              with and without an S1 author (P-295); that ``attempt_error`` caps the detail
              never the prefix; that the transcript is written to a file, never inlined; that
              the sighted test command is best-effort and brings the oracle services up
              (mesh-client, DL-024); that every exit of ``build``, an S1 authoring failure and
              a calibrated budget profile's attempt record where the builder ran
              (``builder_executor``, P-795); and that a run climbs the ladder (rung 1 red →
              rung 2 gold clean) into two chained rows.
How:          ``FakeBuilder`` registered as ``fake`` with a scripted behaviour → ``adapter`` /
              ``run`` over ``pyrepo`` with the real ``PytestRunner`` and ``LocalExecutor``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/builders/adapter.py (under test), src/crb/builders/base.py (the brief,
              budget, ladder and outcome contract), src/crb/core/run.py (the orchestrator the
              adapter feeds), src/crb/core/ledger.py (the rows and chain asserted),
              tests/fixtures/pyrepo.py, tests/test_worker.py (the same adapter under the worker)
Tested by:    tests/test_builders_adapter.py
Touch when:   never for a new repository; adding a builder (its outcome shapes must map to these
              error rules — add a case per new stop reason); the brief gains a field (the no-leakage
              cases must still hold in both modes).
"""

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
from crb.builders.brief import LABEL_CONTEXT_ARM, S1Arm
from crb.builders.container import BuilderContainerSettings
from crb.core.checks import RepoChecks, resolve
from crb.core.execution import LocalExecutor
from crb.core.grade import MODE_SIGHTED, MODES, Belts
from crb.core.ledger import GradeRow, JsonlLedger, grade_row_from_result, verify_chain
from crb.core.lint import LintPlan, LintTool
from crb.core.prevention import AUTO_CONFIG, AUTO_CONTEXT, AUTO_OFF, LearningSnapshot
from crb.core.run import BuildAttempt, RunSpec, run
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.posture import posture_result, witnessed_context_for

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
        if self.behaviour.startswith("ugly_gold"):
            # a correct patch the repository's formatter rejects; a REPAIR call cleans it
            src = workspace.root / pr.SRC
            if brief.repair_note and self.behaviour == "ugly_gold_repair_error":
                # the repair call never reached the model (a 429, a dead credential)
                return BuildOutcome(
                    **base,
                    stop_reason=STOP_MODEL_ERROR,
                    errors=("model_error: 429 rate limited",),
                    cost_usd=0.005,
                )
            if brief.repair_note:
                src.write_text(src.read_text().replace("UGLY = 1\n", ""), encoding="utf-8")
            else:
                pr.apply_gold(workspace)
                src.write_text(src.read_text() + "UGLY = 1\n", encoding="utf-8")
            return BuildOutcome(
                **base,
                done=True,
                stop_reason=STOP_DONE,
                cost_usd=0.01,
                latency_s=0.1,
                budget=budget,
            )
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
    """The real instrument as keyword arguments: ``PytestRunner``,
    ``LocalExecutor`` and the config.
    """
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


# --- build_fn: the run's arm ----------------------------------------------------------------

#: RED at ``pyrepo``'s parent (the feat commit adds ``subtract``, never ``multiply``)
_S1_TEST = (
    "tests/test_s1_multiply.py",
    "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
)

#: the loop switch as a run can hold it: no snapshot, off, opted out, and the two on settings
_LOOP: dict[str, LearningSnapshot | None] = {
    "none": None,
    "off": LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_OFF),
    "opted_out": LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_CONTEXT, opted_out=True),
    "context": LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_CONTEXT),
    "config": LearningSnapshot(repo=pr.REPO_NAME, auto_apply=AUTO_CONFIG),
}


def _authored(_ws: Any, _subject: str, _message: str) -> tuple[str, str]:
    return _S1_TEST


def _author_raises(_ws: Any, _subject: str, _message: str) -> tuple[str, str]:
    raise RuntimeError("the author fell over")


@pytest.mark.parametrize("author", [None, "t1"])
@pytest.mark.parametrize("loop", list(_LOOP))
@pytest.mark.parametrize("mode", MODES)
def test_run_arm_for_matches_the_closure_for_every_mode(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],
    mode: str,
    loop: str,
    author: str | None,
) -> None:
    """``run_arm_for`` is the arm the build closure stamps on every attempt of a run, so a
    caller outside the closure names the same arm the rows will carry (P-295). The closure
    stamps it on three exits: a refusal before the brief is composed (an unknown rung), the
    composed brief, and on the ``S1`` arm an authoring failure. ``MODES`` is every mode the
    closure is handed: a ``replay`` run builds sighted, a ``blind`` run blind, and
    ``RunSpec`` refuses any other mode."""
    learning = _LOOP[loop]
    base = f"S1@{author}" if author else ("S3" if mode == MODE_SIGHTED else "A0")
    expected = base + ("+L" if loop in ("context", "config") else "")

    def stamped(s1: S1Arm | None, rung: str, name: str) -> str:
        fn = adapter.build_fn_for(
            _ladder("noop"), budget=Budget(), learning=learning, s1=s1, **harness
        )
        ws = pyrepo.trial(tmp_path / name, overlay_tests=mode == MODE_SIGHTED)
        try:
            attempt = fn(ws, pyrepo.feat_task(), mode, rung)
        finally:
            ws.remove()
        return attempt.labels[LABEL_CONTEXT_ARM]

    s1 = S1Arm(author=_authored, author_model=author) if author else None
    exits = {
        "refused": stamped(s1, "fake:zzz", "refused"),
        "composed": stamped(s1, "fake:m0", "composed"),
    }
    if author:
        exits["authoring"] = stamped(
            S1Arm(author=_author_raises, author_model=author), "fake:m0", "authoring"
        )
    assert adapter.run_arm_for(mode, learning=learning, s1_author_model=author) == expected
    assert exits == dict.fromkeys(exits, expected)


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
        harness["runner"], harness["executor"], tmp_path, ("tests/test_x.py",), deps=None
    )
    assert "-m pytest" in cmd and cmd.endswith("tests/test_x.py")

    class Broken(PytestRunner):
        def command(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("no")

    assert (
        adapter.sighted_test_command(
            Broken(harness["config"]), harness["executor"], tmp_path, ("t",), deps=None
        )
        == ""
    )


def test_sighted_test_command_brings_the_services_up_and_exports_their_env(
    harness: dict[str, Any], tmp_path: Path
) -> None:
    """mesh-client: the grader had the MESH sandbox and the builder did not, so it ran
    `docker ps` / `curl localhost:8701` itself and was refused (2026-09-15). With
    services declared, the era's services are ensured before the build and their
    environment is part of the command the brief shows."""
    calls: list[tuple[Path, str | None]] = []

    class WithServices(PytestRunner):
        def has_services(self) -> bool:
            return True

        def ensure_services(
            self, executor: Any, root: Path, *, authored: Any = None, on_command: Any = None
        ) -> Any:  # type: ignore[override]
            calls.append((Path(root), authored))
            return ()

        def service_env(self) -> dict[str, str]:
            return {"MESH_SANDBOX_URL": "https://localhost:8701", "MESH_CA": "/certs/ca.pem"}

    cmd = adapter.sighted_test_command(
        WithServices(harness["config"]),
        harness["executor"],
        tmp_path,
        ("tests/test_x.py",),
        authored="2025-01-02T03:04:05+00:00",
        deps=None,
    )
    assert calls == [(tmp_path, "2025-01-02T03:04:05+00:00")]
    assert "MESH_SANDBOX_URL=https://localhost:8701" in cmd and "MESH_CA=/certs/ca.pem" in cmd
    assert cmd.endswith("tests/test_x.py")

    class ServiceDown(WithServices):
        def ensure_services(self, *a: Any, **k: Any) -> Any:  # type: ignore[override]
            raise RuntimeError("compose failed")

    # a service that cannot come up is the grader's harness error to record, not a
    # brief with a half-environment: best effort yields ""
    assert (
        adapter.sighted_test_command(
            ServiceDown(harness["config"]), harness["executor"], tmp_path, ("t",), deps=None
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
        context_for=witnessed_context_for(
            pyrepo.repo,
            pyrepo.config,
            runner=harness["runner"],
            executor=harness["executor"],
            scratch=tmp_path / "scratch",
        ),
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
        context_for=witnessed_context_for(
            pyrepo.repo,
            pyrepo.config,
            runner=harness["runner"],
            executor=harness["executor"],
            scratch=tmp_path / "scratch",
        ),
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
        context_for=witnessed_context_for(
            pyrepo.repo,
            pyrepo.config,
            runner=harness["runner"],
            executor=harness["executor"],
            scratch=tmp_path / "scratch",
        ),
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


# --- belt-5 pre-flight ------------------------------------------------------------------


_FAKE_RUFF = """#!/usr/bin/env python3
import sys
args = sys.argv[1:]
files = [a for a in args if a.endswith(".py")]
fix = "--fix" in args or (args[:1] == ["format"] and "--check" not in args)
rc = 0
for f in files:
    text = open(f, encoding="utf-8").read()
    if "UGLY" in text:
        if fix:
            open(f, "w", encoding="utf-8").write(text.replace("UGLY = 1\\n", ""))
        else:
            print(f"{f}:1:1: X001 ugly")
            rc = 1
sys.exit(rc)
"""


class _RuffRunner(PytestRunner):
    """The fixture repo declares no linter; this runner plans a fake ``ruff`` whose check
    rejects a file containing ``UGLY`` and whose ``--fix`` removes it."""

    script: str = ""

    def lint_plan(self, root: Path, executor: Any) -> LintPlan | None:
        return LintPlan(
            (LintTool("ruff", (self.script, "check", "--no-fix"), exts=(".py",)),),
            detected="fake-ruff",
        )


def _preflight_run(
    pyrepo: pr.PyRepo, tmp_path: Path, preflight: adapter.Preflight | None, behaviour: str
) -> tuple[list[Any], list[tuple[str, dict[str, Any]]]]:
    script = tmp_path / "fake-ruff"
    script.write_text(_FAKE_RUFF, encoding="utf-8")
    script.chmod(0o755)
    runner = _RuffRunner(pyrepo.config)
    runner.script = str(script)
    ladder = _ladder(behaviour)
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-preflight",
        config=pyrepo.config,
        runner=runner,
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        ledger=ledger,
        evidence_dir=tmp_path / "evidence",
        ladder=adapter.ladder_labels(ladder),
        context_for=witnessed_context_for(
            pyrepo.repo,
            pyrepo.config,
            runner=runner,
            executor=LocalExecutor(),
            scratch=tmp_path / "scratch",
            # the gold passes the fake linter, so a belt-5 rejection is the model's (the
            # ADR-0019 witness #57's repair-merge case needs to see a lint row, not an
            # environment one)
            gold_lint=True,
        ),
    )
    events: list[tuple[str, dict[str, Any]]] = []
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=runner,
        executor=LocalExecutor(),
        config=pyrepo.config,
        on_event=lambda a, p: events.append((a, dict(p))),
        preflight=preflight,
    )
    run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    return list(ledger.rows()), events


def test_without_preflight_a_correct_but_unformatted_patch_fails_belt_5(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    (row,), _ = _preflight_run(pyrepo, tmp_path, None, "ugly_gold")
    assert row.target_green is True and row.repo_lint_clean is False and row.clean is False
    assert row.builder == "fake" and "preflight" not in row.labels


def test_preflight_fixers_clear_a_formatter_rejection(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """Stage A (2026-09-15): the repository's own fixer flips a prettier/ruff-format
    rejection with no model call. The arm is recorded as a different builder."""
    (row,), events = _preflight_run(
        pyrepo, tmp_path, adapter.Preflight(fix=True, repair_turns=0), "ugly_gold"
    )
    assert row.clean is True and row.repo_lint_clean is True
    assert row.builder == "fake+preflight"
    assert row.labels["preflight"] == "fix=1,repair=0;before=rejected;fix=ruff:0;after_fix=clean"
    assert [a for a, _ in events if a.startswith("builder.preflight")] == [
        "builder.preflight.rejected",
        "builder.preflight.fixed",
    ]
    assert len(FakeBuilder.briefs) == 1  # no repair call was needed
    assert row.cost_usd == 0.01


def test_a_preflight_repair_that_ends_in_a_model_error_keeps_the_first_patch(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The pre-flight's repair call and the finish gate's share one merge: a repair that
    never reached the model leaves the first build's patch to be graded, never an errored
    attempt whose edits are thrown away (CodeRabbit, PR #57)."""
    (row,), events = _preflight_run(
        pyrepo, tmp_path, adapter.Preflight(fix=False, repair_turns=1), "ugly_gold_repair_error"
    )
    assert row.error == "" and row.target_green is True
    assert row.repo_lint_clean is False and not row.clean  # belt 5 still judges the patch
    assert "after_repair=repair_error" in row.labels["preflight"]
    assert not any(a == "builder.discard" for a, _ in events)
    assert row.cost_usd == pytest.approx(0.015)


def test_a_repair_merge_keeps_the_first_stop_unless_the_repair_violated() -> None:
    base = {"builder": "b", "model": "m", "provider": "p", "mode": "sighted"}
    first = BuildOutcome(**base, done=True, stop_reason=STOP_DONE, cost_usd=0.01)
    errored = BuildOutcome(
        **base, stop_reason=STOP_MODEL_ERROR, errors=("model_error: 429",), cost_usd=0.005
    )
    merged = adapter._merge_outcomes(first, errored)
    assert adapter.attempt_error(merged) == "" and merged.done is True
    assert merged.stop_reason == STOP_DONE and merged.cost_usd == pytest.approx(0.015)
    done = BuildOutcome(**base, done=False, stop_reason=STOP_DONE, cost_usd=0.02)
    assert adapter._merge_outcomes(first, done).done is False  # a finished repair is last


def test_preflight_repair_turn_is_one_bounded_build_with_the_findings(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    (row,), events = _preflight_run(
        pyrepo, tmp_path, adapter.Preflight(fix=False, repair_turns=1), "ugly_gold"
    )
    assert row.clean is True and row.repo_lint_clean is True and row.builder == "fake+preflight"
    assert row.labels["preflight"] == "fix=0,repair=1;before=rejected;after_repair=clean;repair=1"
    first, second = FakeBuilder.briefs
    assert first.repair_note == "" and "[ruff] rc=1" in second.repair_note
    assert "X001 ugly" in second.repair_note and "REPAIR:" in second.task_text()
    assert row.cost_usd == 0.02  # both calls are one attempt's spend
    assert any(a == "builder.preflight.repaired" for a, _ in events)


# --- build_fn: where the builder ran, on every exit (P-795) ---------------------------------

#: the posture class a sealed worker grades in: the row is sealed only when it also records
#: that its builder ran in the sealed container (``GradeRow.sealed`` fails closed)
_SEALED_CLASS = "docker/inplace/sealed"
_CONTAINER = BuilderContainerSettings(image="crb-builder:test", user="10001:10001")


class _Session:
    """Stands in for :class:`ContainerSession`: no daemon, no overrides."""

    def __init__(self, settings: BuilderContainerSettings, checkout: Any, **kw: Any) -> None:
        self.checkout = checkout

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def overrides_for(self, builder: str) -> dict[str, Any]:
        return {}


def _sealed_row(attempt: BuildAttempt, task: TaskSpec, mode: str, tmp_path: Path) -> GradeRow:
    """The row the sealed worker writes for ``attempt``, appended through the ledger."""
    belts = Belts(True, False, True, False, None)
    result = posture_result(
        task.task_id, pr.REPO_NAME, mode, False, belts, posture_class=_SEALED_CLASS
    )
    row = grade_row_from_result(
        result,
        task,
        pack_hash="h" * 64,
        builder=attempt.builder,
        builder_error=attempt.error,
        labels=dict(attempt.labels),
    )
    return JsonlLedger(tmp_path / "ledger.jsonl").append(row)


def _no_tool(*_a: Any, **_kw: Any) -> str:
    return "pytest is not installed in the sandbox"


def _harness_down(*_a: Any, **_kw: Any) -> str:
    raise RuntimeError("the harness could not describe its command")


_LEAK_CHECKS = {
    "finish_gate": True,
    "commands": [{"name": "peek", "argv": ["pytest", pr.TEST_SUBTRACT], "blind_only": True}],
}

#: every exit of ``build`` — (rung label, ladder behaviour, mode, what the exit is): the
#: refusals before any builder ran, the authoring failure, a builder that raised, and a build
_EXITS: dict[str, tuple[str, str, str, str]] = {
    "unknown_rung": ("fake:zzz", "noop", "sighted", "unknown rung"),
    "runner_tool_missing": ("fake:m0", "noop", "sighted", "not installed"),
    "builder_unavailable": ("no-such-builder:m", "noop", "sighted", "builder unavailable"),
    "harness_raised": ("fake:m0", "noop", "sighted", "RuntimeError"),
    "finish_gate_refused": ("fake:m0", "noop", "blind", "finish gate refused"),
    "s1_authoring_failed": ("fake:m0", "noop", "sighted", "authoring"),
    "builder_raised": ("fake:m0", "raise", "sighted", "builder raised"),
    "built": ("fake:m0", "noop", "sighted", ""),
}


@pytest.mark.parametrize("exit_", list(_EXITS))
def test_every_early_exit_of_build_stamps_the_executor(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    exit_: str,
) -> None:
    """A sealed run's row is read by a registered reading only when it records that its
    builder ran in the sealed container. Every exit but the last two once left
    ``builder_executor`` off, so a sealed miss read unsealed, a reading dropped it, and the
    commit read pending — re-rolled until it was clean (the Wave 3 red team on c5b9e5ec)."""
    rung_label, behaviour, mode, says = _EXITS[exit_]
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"fake", "no-such-builder"}))
    if exit_ == "runner_tool_missing":
        monkeypatch.setattr(adapter, "runner_tool_missing", _no_tool)
    if exit_ == "harness_raised":
        monkeypatch.setattr(adapter, "sighted_test_command", _harness_down)
    ladder = (
        EscalationLadder((Rung("no-such-builder", "m"),))
        if exit_ == "builder_unavailable"
        else _ladder(behaviour)
    )
    checks = (
        resolve(RepoChecks.from_config(_LEAK_CHECKS), None)
        if exit_ == "finish_gate_refused"
        else None
    )
    s1 = S1Arm(author=_author_raises, author_model="t1") if exit_ == "s1_authoring_failed" else None
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        container=_CONTAINER,
        session_factory=_Session,
        checks=checks,
        s1=s1,
        **harness,
    )
    task = pyrepo.feat_task()
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=mode == MODE_SIGHTED)
    try:
        attempt = fn(ws, task, mode, rung_label)
    finally:
        ws.remove()
    assert (says in attempt.error) if says else attempt.error == ""
    assert attempt.labels.get("builder_executor") == "docker"
    row = _sealed_row(attempt, task, mode, tmp_path)
    assert row.sealed and row.builder_executor == "docker"


def test_a_calibrated_budget_profile_keeps_builder_executor_docker(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The calibrated budget profile's labels once REPLACED the executor stamp, so every row
    of a calibrated sealed run read unsealed and no reserved.v1 reading (which requires a
    budget profile) could count one. Its labels are kept; the executor is the adapter's,
    whatever the profile says."""
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"fake"}))
    profile = {"budget_profile": "calibrated", "budget_tier": "XS", "builder_executor": "host"}

    def calibrated(_t: TaskSpec, _m: str, _r: Rung, b: Budget) -> tuple[Budget, dict[str, str]]:
        return b, dict(profile)

    task = pyrepo.feat_task()
    for behaviour in ("noop", "raise"):  # the build, and a builder that raised
        fn = adapter.build_fn_for(
            _ladder(behaviour),
            budget=Budget(),
            container=_CONTAINER,
            session_factory=_Session,
            budget_for_task=calibrated,
            **harness,
        )
        ws = pyrepo.trial(tmp_path / behaviour)
        try:
            attempt = fn(ws, task, "sighted", "fake:m0")
        finally:
            ws.remove()
        assert attempt.labels["budget_profile"] == "calibrated"
        assert attempt.labels["budget_tier"] == "XS"
        assert attempt.labels["builder_executor"] == "docker"
        row = _sealed_row(attempt, task, "sighted", tmp_path / behaviour)
        assert row.sealed and row.labels["budget_profile"] == "calibrated"


def test_an_s1_authoring_failure_under_docker_is_sealed(
    pyrepo: pr.PyRepo, tmp_path: Path, harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ``S1`` authoring failure is the arm's miss (ADR-0026 item 1, DL-360) and its row
    carries the rung's builder, model and provider, so it is in the reading's cell. It once
    carried no executor, so under docker it read unsealed and the reading never saw the
    miss; off docker it reads host, as the builder would have run."""
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"fake"}))
    task = pyrepo.feat_task()
    for container, want in ((_CONTAINER, "docker"), (None, "host")):
        fn = adapter.build_fn_for(
            _ladder("gold"),
            budget=Budget(),
            container=container,
            session_factory=_Session,
            s1=S1Arm(author=_author_raises, author_model="t1"),
            **harness,
        )
        ws = pyrepo.trial(tmp_path / want)
        try:
            attempt = fn(ws, task, "sighted", "fake:m0")
        finally:
            ws.remove()
        assert attempt.error.startswith("authoring:") and FakeBuilder.briefs == []
        assert (attempt.builder.name, attempt.builder.model) == ("fake", "m0")
        assert attempt.labels["builder_executor"] == want
        assert attempt.labels[LABEL_CONTEXT_ARM] == "S1@t1"
        row = _sealed_row(attempt, task, "sighted", tmp_path / want)
        assert row.sealed is (want == "docker")
        assert row.failure_kind == "authoring"
