"""The sealed-posture proof on cobra 746ef07 — the product's own code paths, no builder, no model.

Run with PYTHONPATH=<worktree>/src and the provisioning environment set (see the review).
Prints one JSON object per step to stdout; writes the whole record to proof.json.

Navigation
----------
What it is:   The sealed-posture review's proof script — the worker's own posture gate,
              qualifier, grader and run loop driven on one real task, with no builder and no
              model.
What it does: Qualifies cobra 746ef07 in docker/copy/sealed with its modules fetched and
              sealed, replays the gold clean through the run's gate, empties the sealed cache
              and shows the run stop BUNDLE_INTEGRITY before any builder call, grades a trial
              past the gate as harness (never builder_red) and re-qualifies it
              QUAL_ENV_UNLOADABLE. It spends nothing and writes only under its CRB_HOME.
How:          The environment crbp.sh exports → ``make_deps_provider`` and ``PostureGate``
              → ``qualify_task`` → ``run`` with a gold build function and a counting one →
              one JSON line per step, the whole record in proof.json.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   docs/reviews/2026-09-25-sealed-posture.md (the review that cites each step),
              docs/reviews/2026-09-25-sealed-posture/crbp.sh (the environment it runs under),
              docs/reviews/2026-09-25-sealed-posture/proof.json (its recorded output),
              src/crb/server/posture_gate.py (the gate it drives), src/crb/core/qualify.py
              (``qualify_task``), src/crb/core/run.py (the run loop)
Tested by:    untested — a one-off proof on the operator's stack; its output is committed as
              docs/reviews/2026-09-25-sealed-posture/proof.json and re-ran exactly on a
              throwaway CRB_HOME
Touch when:   never — it is the record of a review; a new proof is a new file beside a new
              review.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

from crb.cli.commands import Workdir, build_executor, deps_provider
from crb.cli.commands import repo as repo_cmd
from crb.core.deps import ProvisionRefused
from crb.core.evidence import BuilderRef
from crb.core.git import GitRepo
from crb.core.grade import grade
from crb.core.ledger import JsonlLedger, grade_row_from_result
from crb.core.qualify import JsonlQualifications, qualify_task
from crb.core.run import BuildAttempt, RunSpec
from crb.core.run import run as run_tasks
from crb.core.workspace import Workspace
from crb.provision import make_deps_provider
from crb.provision.config import ProvisionConfig
from crb.server.posture_gate import PostureGate, resolve_run_posture

W = Path(os.environ["CRB_HOME"])
OUT = Path(sys.argv[1])
TASK = "746ef07158728502482cea9f880a6f4b21ef29a9"
record: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def step(name: str, **facts: object) -> None:
    record[name] = facts
    print(json.dumps({"step": name, **facts}, default=str), flush=True)
    OUT.write_text(json.dumps(record, indent=1, default=str))


events: list[tuple[str, dict]] = []


def on_event(action: str, payload: object) -> None:
    events.append((action, dict(payload)))  # type: ignore[arg-type]


wd = Workdir(W)
config, clone = wd.require_clone("cobra")
repo = GitRepo(clone)
task = wd.find_task("cobra", TASK)
runner = repo_cmd.bound_runner(config, repo_cmd.env_dir_of(wd, "cobra"))
executor = build_executor("docker", config)
provider = deps_provider(executor)
posture = resolve_run_posture(executor, runner, config, provider, root=clone)
step(
    "posture",
    posture_id=posture.posture_id,
    posture_class=posture.posture_class,
    posture=posture.to_dict(),
    provider=type(provider).__name__,
)

# --- (a) + (b): the qualification the miner recorded in this posture --------------------
quals = JsonlQualifications(wd.qualification_file("cobra"))
q = quals.latest(TASK, posture.posture_id)
assert q is not None, "no qualification in this posture — run crb mine / crb repo qualify first"
qd = q.to_dict()
step(
    "qualification",
    state=q.state,
    code=q.code,
    qualified=q.is_qualified,
    posture_id=qd.get("posture_id"),
    deps=qd.get("deps"),
    env_probe=qd.get("env_probe"),
    red=qd.get("red"),
    baseline=qd.get("baseline"),
    gold=qd.get("gold"),
    fingerprint=qd.get("fingerprint"),
)

scratch = W / "scratch"
scratch.mkdir(parents=True, exist_ok=True)


def gate() -> PostureGate:
    return PostureGate(
        repo=repo,
        config=config,
        runner=runner,
        executor=executor,
        scratch=scratch,
        provider=provider,
        posture=posture,
        run_id="proof-" + time.strftime("%H%M%S"),
        on_event=on_event,
    )


def spec_for(g: PostureGate, name: str) -> RunSpec:
    return RunSpec(
        run_id=g.run_id + "-" + name,
        config=config,
        runner=runner,
        executor=executor,
        scratch=scratch,
        ledger=JsonlLedger(W / f"ledger-{name}.jsonl"),
        evidence_dir=W / f"evidence-{name}",
        context_for=g.context_for,
        posture=posture.to_dict(),
    )


calls = {"gold": 0, "counting": 0}


def gold_fn(ws: Workspace, t, mode: str, rung: str) -> BuildAttempt:
    """The fixture_gold instrument check: overlay the commit's own source change."""
    calls["gold"] += 1
    ws.overlay_sources(t.src_files)
    return BuildAttempt(BuilderRef(name="fixture_gold", model="gold", provider="fixture", mode=mode))


def counting_fn(ws: Workspace, t, mode: str, rung: str) -> BuildAttempt:
    calls["counting"] += 1
    return BuildAttempt(BuilderRef(name="counting", model="none", provider="fixture", mode=mode))


# --- positive control: a clean gold replay through the run's gate ------------------------
g1 = gate()
admitted = g1.admit([task], known={TASK: q})
t0 = time.monotonic()
summary = run_tasks(spec_for(g1, "gold"), repo, admitted, gold_fn, on_event=on_event)
rows = list(JsonlLedger(W / "ledger-gold.jsonl").rows())
step(
    "gold_replay",
    rows=[{"clean": r.clean, "target_green": r.target_green, "no_new_failures": r.no_new_failures, "failure_kind": r.failure_kind, "error": r.error,
           "builder": r.builder, "labels": dict(r.labels)} for r in rows],
    admitted=[t.task_id for t in admitted],
    summary=summary.to_dict(),
    builder_calls=calls["gold"],
    seconds=round(time.monotonic() - t0, 1),
)
ctx_saved = g1.context_for(task)
deps = g1.deps_for(task)

# --- break the environment: empty the sealed module cache (the manifest stays) -----------
sealed = Path(os.environ["CRB_PROVISION__STORE"]) / "go" / deps.gold.key
gomod = sealed / "gomod"
removed = 0
for d, dirs, files in os.walk(gomod, topdown=False):
    dp = Path(d)
    dp.chmod(dp.stat().st_mode | stat.S_IWUSR)
for d, dirs, files in os.walk(gomod, topdown=False):
    dp = Path(d)
    for f in files:
        (dp / f).unlink()
        removed += 1
    for sd in dirs:
        (dp / sd).rmdir()
gomod.chmod(0o555)
step("broken", sealed_set=str(sealed), files_removed=removed, left=sorted(os.listdir(gomod)))

# --- (c-i) the run's gate refuses BEFORE any builder call ---------------------------------
g2 = gate()
admitted2 = g2.admit([task], known={TASK: q})
refused = None
try:
    run_tasks(spec_for(g2, "broken"), repo, admitted2, counting_fn, on_event=on_event)
except ProvisionRefused as exc:
    refused = exc.to_dict()
ledger_broken = W / "ledger-broken.jsonl"
step(
    "gate_refuses",
    refusal=refused,
    builder_calls=calls["counting"],
    rows_written=(
        sum(1 for _ in ledger_broken.open()) if ledger_broken.exists() else 0
    ),
)

# --- (c-ii) past the gate: the grade itself never blames the model -------------------------
ws = Workspace.create(repo, TASK, scratch / "proof-noop", config=config)
try:
    ws.overlay_tests(task.test_files)  # a builder that changed nothing
    res = grade(ws, ctx_saved.spec(task), ctx=ctx_saved, config=config, runner=runner,
                executor=executor, on_event=on_event)
    row = grade_row_from_result(
        res, ctx_saved.spec(task), pack_hash="0" * 64,
        builder=BuilderRef(name="counting", model="none", provider="fixture", mode="sighted"),
    )
    step(
        "grade_past_the_gate",
        failure_kind=row.failure_kind,
        clean=row.clean,
        error=(row.error or "")[:400],
        blamed=getattr(res, "blamed", None),
        witness=getattr(res, "witness", None) and res.witness.to_dict()
        if hasattr(getattr(res, "witness", None), "to_dict") else getattr(res, "witness", None),
    )
finally:
    ws.remove()

# --- (c-iii) qualifying again in the broken environment ------------------------------------
q2 = qualify_task(repo, config, task, posture=posture, deps=provider, runner=runner,
                  executor=executor, scratch=scratch, on_event=on_event)
step("requalify_broken", state=q2.state, code=q2.code, message=q2.message[:300],
     fix=q2.view().get("fix"))

# --- (c-iv) provisioning off (the shipped default) ----------------------------------------
off = make_deps_provider(ProvisionConfig(enabled=False, store=W / "deps-off"),
                         executor_kind="docker")
try:
    qualify_task(repo, config, task, posture=posture, deps=off, runner=runner,
                 executor=executor, scratch=scratch)
    step("provisioning_off", refused=None)
except ProvisionRefused as exc:
    step("provisioning_off", refused=exc.to_dict())

step("events", counts={a: sum(1 for x, _ in events if x == a) for a in sorted({x for x, _ in events})})
