"""crb.core.run — the orchestrator grades under the same worktree-integrity pre-flight
as the CLI (independent review pass, 2026-09-14, finding 1(b): ``run_task`` graded a
worktree whose builder had committed the poison ``clean``; the CLI pinned HEAD, the
run path did not).

Navigation
----------
What it is:   The orchestrator's regression suite for the worktree-integrity pre-flight
              (independent review pass 2026-09-14, finding 1(b)).
What it does: Pins that ``run_task`` disqualifies a worktree whose builder committed the poison
              or hid it in ``info/exclude`` — the CLI pinned HEAD, the run path did not — and
              that an honest gold still grades clean under the same pre-flight. Pins that no
              fragment of the held-out commit's sha reaches the builder (worktree path, ``.git``
              pointer, environment, prompt; assessment 2026-09-25 B1), that the run's events map
              the opaque name back to the task and each pack names the worktree its row graded,
              and that no worktree destination in the source tree is built from a commit sha.
How:          A ``RunSpec`` over ``pyrepo`` with a ``BuildAttempt`` that performs the edit; the
              ledger row is read back and the chain verified. The leakage cases drive the real
              ``claude_code`` adapter with a recording spawn (tests/fixtures/leakage.py) and scan
              what it was handed with the fixture's real sha; the source ratchet reads
              ``src/crb`` line by line.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/run.py (under test), src/crb/core/workspace.py
              (``enforce_integrity``, ``opaque_dest``), tests/fixtures/leakage.py (the sha
              scan), tests/test_builders_adapter.py (the full ``run`` end to end),
              tests/test_grade.py (the same findings at the grader)
Tested by:    tests/test_run.py
Touch when:   a new integrity violation is added to the workspace (mirror the case here so the
              run path and the CLI stay in step); a new place creates a worktree a builder or a
              grader runs in (it must take ``opaque_dest``, or the ratchet here fails).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from crb.builders.adapter import build_fn_for, ladder_from_spec
from crb.builders.base import Budget
from crb.core.evidence import BuilderRef
from crb.core.execution import LocalExecutor
from crb.core.ledger import JsonlLedger, verify_chain
from crb.core.run import BuildAttempt, RunSpec, run_task
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.leakage import RecordingSpawn, leaks

_POISON = 'import calc as _m\nexec("def subtract(a, b):\\n    return a - b\\n", _m.__dict__)\n'


def _spec(pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp: Path) -> RunSpec:
    return RunSpec(
        run_id="run-integrity",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp / "scratch",
        ledger=JsonlLedger(tmp / "ledger.jsonl"),
        evidence_dir=tmp / "evidence",
        ladder=("r1", "r2"),
    )


def _attempt() -> BuildAttempt:
    return BuildAttempt(BuilderRef(name="fixture", model="m", provider="p", mode="sighted"))


def test_run_task_disqualifies_a_worktree_whose_builder_committed_the_poison(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        (ws.root / "conftest.py").write_text(_POISON, encoding="utf-8")
        with (ws.root / pr.SRC).open("a", encoding="utf-8") as fh:
            fh.write("# touched\n")
        pr.git(ws.root, "add", "-f", "conftest.py")
        pr.git(ws.root, "commit", "-q", "-m", "hide the poison")
        return _attempt()

    events: list[tuple[str, dict[str, Any]]] = []
    spec = _spec(pyrepo, runner, executor, tmp_path)
    outcome = run_task(
        spec, pyrepo.repo, feat_task, build_fn, on_event=lambda a, p: events.append((a, dict(p)))
    )
    assert outcome.clean is False and outcome.disqualified is True
    assert outcome.attempts == 1  # a disqualified attempt stops the ladder
    (row,) = outcome.rows
    assert row.disqualified and row.dq_reason.startswith("worktree integrity")
    assert row.tests_unmodified is False and row.clean is False
    assert row.failure_kind == "disqualified"
    assert verify_chain(spec.ledger.rows()) == 1
    tamper = [p for a, p in events if a == "grade.tamper"]
    assert tamper and tamper[0]["kind"] == "worktree" and tamper[0]["files"] == [".git/HEAD"]


def test_run_task_disqualifies_a_poison_hidden_in_info_exclude(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    exclude = pyrepo.path / ".git" / "info" / "exclude"

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        (ws.root / "conftest.py").write_text(_POISON, encoding="utf-8")
        with (ws.root / pr.SRC).open("a", encoding="utf-8") as fh:
            fh.write("# touched\n")
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write("conftest.py\n")
        return _attempt()

    spec = _spec(pyrepo, runner, executor, tmp_path)
    outcome = run_task(spec, pyrepo.repo, feat_task, build_fn)
    assert outcome.clean is False and outcome.disqualified is True
    (row,) = outcome.rows
    assert "info/exclude" in row.dq_reason
    assert "conftest.py" not in exclude.read_text(
        encoding="utf-8"
    )  # the shared file is clean again


def test_run_task_honest_gold_is_clean_under_the_pre_flight(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        pr.apply_gold(ws)
        return _attempt()

    spec = _spec(pyrepo, runner, executor, tmp_path)
    outcome = run_task(spec, pyrepo.repo, feat_task, build_fn)
    assert outcome.clean is True and outcome.attempts == 1
    (row,) = outcome.rows
    assert row.clean and row.evidence_pack_hash and row.failure_kind == ""


# ---------------------------------------------------------------------------
# B1 (assessment 2026-09-25): the held-out commit's sha never reaches the builder
# ---------------------------------------------------------------------------


def _claude_build_fn(spec: RunSpec, spawn: RecordingSpawn, **kw: Any) -> Any:
    """The real ``claude_code`` adapter path with the CLI process replaced by ``spawn``."""
    return build_fn_for(
        ladder_from_spec(["claude_code:claude-opus-5"]),
        budget=Budget(max_turns=5, max_tool_calls=10, wall_clock_s=60),
        runner=spec.runner,
        executor=spec.executor,
        config=spec.config,
        builder_overrides={
            "spawn": spawn,
            "claude_binary": "/fake/claude",
            "keep_transcript": True,
        },
        **kw,
    )


@pytest.mark.parametrize("mode", ["sighted", "blind"])
def test_the_builder_is_handed_no_fragment_of_the_task_sha(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """The worktree path, its ``.git`` pointer, the builder's environment and its prompt
    (argv) carry no 7-character substring of the task's real sha, in either mode."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real-0000000000000000")
    sha = feat_task.task_id
    assert len(sha) == 40  # the fixture's REAL commit sha, not a stand-in
    spec = RunSpec(
        run_id="run-leak",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp_path / "scratch",
        ledger=JsonlLedger(tmp_path / "ledger.jsonl"),
        evidence_dir=tmp_path / "evidence",
        mode=mode,
        ladder=("claude_code:claude-opus-5",),
    )
    spawn = RecordingSpawn()
    events: list[tuple[str, dict[str, Any]]] = []
    run_task(
        spec,
        pyrepo.repo,
        feat_task,
        _claude_build_fn(spec, spawn),
        on_event=lambda a, p: events.append((a, dict(p))),
    )
    assert spawn.cwd is not None, "the builder was never started"
    assert leaks(sha, str(spawn.cwd)) == [], f"worktree path {spawn.cwd}"
    assert leaks(sha, spawn.git_file) == [], f".git pointer {spawn.git_file!r}"
    assert leaks(sha, *(f"{k}={v}" for k, v in spawn.env.items())) == []
    assert leaks(sha, *spawn.argv) == [], "the prompt names the sha"
    # the mapping lives in the run's events, never in the path
    (prep,) = [p for a, p in events if a == "prep.start"]
    assert prep["task"] == sha and prep["worktree"] == spawn.cwd.name


def test_every_attempt_gets_its_own_opaque_worktree(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    """Two rungs of one task: two distinct names, neither derived from the task or the run."""
    seen: list[Path] = []

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        seen.append(ws.root)
        return _attempt()  # an empty build: not clean, so the ladder climbs

    spec = _spec(pyrepo, runner, executor, tmp_path)
    run_task(spec, pyrepo.repo, feat_task, build_fn)
    assert len(seen) == 2 and seen[0] != seen[1]
    for root in seen:
        assert leaks(feat_task.task_id, root.name) == []
        assert spec.run_id not in root.name


def test_every_pack_names_the_worktree_its_row_graded(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    """PR #53 review, fifth round: the route found a row's worktree through the latest
    ``prep.start`` of its run, task and trial, but a reclaimed run writes two rows under
    one trial, so that key does not name one attempt. The pack is written once per
    attempt and its hash is on the row: ``notes.worktree`` there binds the row to the
    worktree it graded. A builder's own notes cannot replace it."""
    seen: list[str] = []

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        seen.append(ws.root.name)
        return BuildAttempt(
            BuilderRef(name="fixture", model="m", provider="p", mode="sighted"),
            notes={"worktree": "run-" + "0" * 12},  # a builder naming another worktree
        )

    events: list[tuple[str, dict[str, Any]]] = []
    spec = _spec(pyrepo, runner, executor, tmp_path)
    outcome = run_task(
        spec, pyrepo.repo, feat_task, build_fn, on_event=lambda a, p: events.append((a, dict(p)))
    )
    named = [p["worktree"] for a, p in events if a == "prep.start"]
    packs = [json.loads((spec.evidence_dir / f"{h}.json").read_text()) for h in outcome.packs]
    assert len(packs) == 2
    assert [p["notes"]["worktree"] for p in packs] == named == seen


#: Where a worktree destination is built: a path joined with an f-string.
_DEST = re.compile(r"/\s*f[\"'][^\"']*\{[^}]*(short_id|sha\[|task_id\[|\.sha\b|task_id\})")
#: Forward mode (the factory): the commit a worktree is named after is the harness's own
#: RED-proven oracle commit or the base the builder already stands on — never a held-out
#: answer. Every other destination must be opaque (``crb.core.workspace.opaque_dest``).
_FORWARD_MODE = {
    "src/crb/factory/build.py",
    "src/crb/factory/review.py",
    "src/crb/factory/testfirst.py",
}


def test_no_worktree_destination_is_built_from_a_commit_sha() -> None:
    """The ratchet for the class, not the instance: a new ``scratch / f"…{task.short_id}…"``
    anywhere outside forward mode fails here before it can reach a builder; and nothing
    under ``crb.builders`` names a task's ``short_id`` (the container label, the transcript
    file) at all."""
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted((root / "src" / "crb").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if rel not in _FORWARD_MODE and _DEST.search(line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
            if rel.startswith("src/crb/builders/") and "short_id" in line:
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert offenders == [], "worktree names built from a commit sha:\n" + "\n".join(offenders)


# --- the structural ratchet: every replay-side worktree is named by ``opaque_dest`` ----------

#: Files that may create a worktree whose name is not drawn by ``opaque_dest``, each with why.
_DEST_EXEMPT: dict[str, str] = {
    "src/crb/core/workspace.py": "the constructors themselves: ``dest`` is their caller's",
    "src/crb/core/git.py": "``worktree_add`` itself",
    "src/crb/cli/commands/grade.py": "``crb prep --dest``: the operator names the directory",
    **dict.fromkeys(
        _FORWARD_MODE, "forward mode: the harness's own oracle commit, never a held-out answer"
    ),
}


#: The ``Workspace`` constructors that create a worktree. They are classmethods, so an
#: instance reaches them too (``ws.create``, ``type(ws).at_ref``): the attribute name is the
#: class, on any receiver but one listed in ``_NOT_A_WORKSPACE`` (PR #53 review, fourth round).
_WS_CTORS = ("create", "at_ref")
#: Receivers, by spelling, whose ``create`` is not a worktree constructor, each with why. A
#: bare name is let off only while the file binds it by ``from … import`` or not at all.
_NOT_A_WORKSPACE: dict[str, str] = {
    "SealedCheckout": "crb.builders.container: an exported copy, never a ``git worktree``",
    "self.client.chat.completions": "the OpenAI SDK client: a chat completion, not a worktree",
}
#: The generics whose subscript index is a type (``Callable[[Workspace], …]``,
#: ``type[Workspace]``); any other subscript (``Box[Workspace]``) may hand its index on.
_GENERICS = frozenset(
    {
        "Annotated", "AsyncIterator", "Awaitable", "Callable", "ClassVar", "Coroutine", "Dict",
        "Final", "FrozenSet", "Generator", "Iterable", "Iterator", "List", "Mapping",
        "Optional", "Sequence", "Set", "Tuple", "Type", "Union", "dict", "frozenset", "list",
        "set", "tuple", "type",
    }
)  # fmt: skip
#: What the ratchet treats as a scope of its own: a name bound in one is not bound in another.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _workspace_names(tree: ast.AST) -> set[str]:
    """The names an import gives ``Workspace``: itself and ``import … Workspace as W``. Any
    other alias (``W = Workspace``, ``W: T = Workspace``, ``(W := Workspace)``, unpacking,
    a container, a return value, an argument) starts with ``Workspace`` used as a value,
    which ``_workspace_as_values`` fails on its own — so no binding form is enumerated here
    (PR #53 review, third round: following only ``=`` left the others through)."""
    names = {"Workspace"}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            names.update(a.asname or a.name for a in n.names if a.name == "Workspace")
    return names


def _type_nodes(tree: ast.AST) -> set[int]:
    """Every node inside an annotation, a known generic's subscript index or a ``type``
    alias: where ``Workspace`` names a type and is never handed on (``ws: Workspace``,
    ``Callable[[Workspace], …]``). Any other subscript index is a value: ``Box[Workspace]``
    can hand it on (PR #53 review, fourth round)."""
    roots: list[ast.AST] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.arg) and n.annotation is not None:
            roots.append(n.annotation)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.returns is not None:
            roots.append(n.returns)
        elif isinstance(n, ast.AnnAssign):
            roots.append(n.annotation)
        elif isinstance(n, ast.Subscript) and _generic(n.value):
            roots.append(n.slice)
        elif isinstance(n, ast.TypeAlias):
            roots.append(n.value)
    return {id(m) for r in roots for m in ast.walk(r)}


def _generic(expr: ast.expr) -> bool:
    """A generic from ``_GENERICS``, by its name or as ``typing.<name>``."""
    return (isinstance(expr, ast.Name) and expr.id in _GENERICS) or (
        isinstance(expr, ast.Attribute) and expr.attr in _GENERICS
    )


def _let_off(tree: ast.AST) -> frozenset[str]:
    """The ``_NOT_A_WORKSPACE`` spellings this file cannot have repointed: a dotted one as
    listed, a bare name only when nothing in the file binds it but ``from … import`` (a
    parameter, an assignment, ``import … as``, a ``def`` or ``class`` of that name each
    make it whatever the file says it is)."""
    bound: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            bound.add(n.id)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.Import):
            bound.update(a.asname or a.name.split(".")[0] for a in n.names)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound.update(n.names)
        elif isinstance(n, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            bound.add(n.rest)
    return frozenset(k for k in _NOT_A_WORKSPACE if "." in k or k not in bound)


def _workspace_as_values(tree: ast.AST, ws: set[str]) -> list[ast.expr]:
    """``Workspace`` (by an imported name or as ``….Workspace``) read anywhere but as the
    receiver of an attribute (``Workspace.create``), as the callee of a plain
    ``Workspace(…)`` (which wraps a directory that exists and creates no worktree) or as a
    type: every way to alias it or hand it on, whose later constructor call the ratchet
    could not attribute."""
    receivers = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    receivers |= {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    types = _type_nodes(tree)
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.Name, ast.Attribute))
        and isinstance(n.ctx, ast.Load)
        and _is_workspace(n, ws)
        and id(n) not in receivers
        and id(n) not in types
    ]


def _is_workspace(expr: ast.expr, names: set[str]) -> bool:
    """``Workspace`` by one of its names, or reached as an attribute (``w.Workspace``)."""
    return (isinstance(expr, ast.Name) and expr.id in names) or (
        isinstance(expr, ast.Attribute) and expr.attr == "Workspace"
    )


def _is_ctor(expr: ast.expr, let_off: frozenset[str]) -> bool:
    """``….create`` / ``….at_ref`` on any receiver the file cannot show is not a
    ``Workspace`` (a class, an alias, an instance, ``type(ws)``), or any ``….worktree_add``."""
    return isinstance(expr, ast.Attribute) and (
        (expr.attr in _WS_CTORS and ast.unparse(expr.value) not in let_off)
        or expr.attr == "worktree_add"
    )


def _dest_arg(call: ast.Call, let_off: frozenset[str]) -> ast.expr | None:
    """The destination a worktree-creating call is handed, or ``None`` when ``call`` creates
    no worktree: ``Workspace.create(repo, sha, dest)`` / ``Workspace.at_ref(repo, ref, dest)``
    and ``<repo>.worktree_add(dest, ref)``, positional or ``dest=``. When the destination
    cannot be read — it travels in ``*args`` / ``**kwargs`` or is missing — the call itself
    is returned: not an ``opaque_dest(...)`` call, so the ratchet cannot admit it."""
    f = call.func
    if not _is_ctor(f, let_off):
        return None
    assert isinstance(f, ast.Attribute)
    pos = 0 if f.attr == "worktree_add" else 2
    for kw in call.keywords:
        if kw.arg == "dest":
            return kw.value
    head = call.args[: pos + 1]
    if len(head) > pos and not any(isinstance(a, ast.Starred) for a in head):
        return call.args[pos]
    return call


def _is_opaque(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "opaque_dest"
    )


def _own(scope: ast.AST) -> list[ast.AST]:
    """The scope's own nodes: a nested function, lambda or class body is its own scope."""
    own: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        own.append(n)
        if not isinstance(n, _SCOPES):
            stack.extend(ast.iter_child_nodes(n))
    return own


def _bindings(scope: ast.AST, own: list[ast.AST]) -> dict[str, list[ast.expr | None]]:
    """Every binding of every name in ``scope``: the value a plain ``name = v`` /
    ``name: T = v`` / ``name += v`` gives it, and ``None`` for every other way a name is
    bound — a parameter, a ``Store`` anywhere else (``with … as``, ``for``, unpacking,
    ``:=``, a comprehension), ``except … as``, ``import … as``, a ``match`` capture and a
    nested ``def`` / ``class``. Enumerating binding FORMS left gaps (PR #53 review); every
    ``Store`` is the class. Bindings made in ANOTHER scope through ``global`` / ``nonlocal``
    are added by ``_scope_bindings``."""
    out: dict[str, list[ast.expr | None]] = {}
    valued: set[int] = set()
    for n in own:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(n.value)
                    valued.add(id(t))
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and isinstance(n.target, ast.Name):
            out.setdefault(n.target.id, []).append(n.value)
            valued.add(id(n.target))
    names: list[str] = []
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope.args
        names += [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
        names += [p.arg for p in (a.vararg, a.kwarg) if p is not None]
    for n in own:
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and id(n) not in valued:
            names.append(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.append(n.name)
        elif isinstance(n, ast.alias):
            names.append(n.asname or n.name.split(".")[0])
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            names.append(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            names.append(n.rest)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(n.name)
    for name in names:
        out.setdefault(name, []).append(None)
    return out


def _declared(own: list[ast.AST], kind: type[ast.Global] | type[ast.Nonlocal]) -> set[str]:
    return {name for n in own if isinstance(n, kind) for name in n.names}


def _scope_bindings(
    tree: ast.Module, scopes: list[ast.AST], owns: dict[int, list[ast.AST]]
) -> dict[int, dict[str, list[ast.expr | None]]]:
    """Each scope's bindings, with the ones other scopes make through it (PR #53 review,
    second round): a nested function's ``nonlocal x; x = v`` adds ``v`` to every enclosing
    scope's ``x``, and any function's ``global x; x = v`` adds ``v`` to the module's. A
    scope that declares ``x`` ``global`` or ``nonlocal`` itself gets a ``None`` for it:
    another function can rebind it between the assignment and the call. Over-counting
    (an intermediate scope that shadows the name) can only fail a call, never admit one."""
    raw = {id(s): _bindings(s, owns[id(s)]) for s in scopes}
    out: dict[int, dict[str, list[ast.expr | None]]] = {}
    for scope in scopes:
        mine = {k: list(v) for k, v in raw[id(scope)].items()}
        own = owns[id(scope)]
        for name in _declared(own, ast.Global) | _declared(own, ast.Nonlocal):
            mine.setdefault(name, []).append(None)
        kind: type[ast.Global] | type[ast.Nonlocal] = ast.Global if scope is tree else ast.Nonlocal
        inner = [n for n in ast.walk(scope) if n is not scope and isinstance(n, _SCOPES)]
        for sub in inner:
            for name in _declared(owns[id(sub)], kind):
                mine.setdefault(name, []).extend(raw[id(sub)].get(name, []))
        out[id(scope)] = mine
    return out


def worktree_dest_offenders(source: str, rel: str) -> list[str]:
    """Every worktree-creating call in ``source`` whose destination is not drawn by
    ``opaque_dest`` — directly, or through a name EVERY binding of which (in its scope, or
    made into it through ``global`` / ``nonlocal``) is an ``opaque_dest(...)`` call — and
    every constructor, or ``Workspace`` itself, handed on as a value
    (``make = Workspace.create``, ``partial(repo.worktree_add, …)``, ``W = Workspace``,
    ``return Workspace``, ``Box[Workspace]``), whose destination is out of sight. A
    ``create`` / ``at_ref`` counts on any receiver (an alias, an instance, ``type(ws)``) but
    one listed in ``_NOT_A_WORKSPACE`` that the file has not rebound. Structural, so no
    spelling of the PATH (``/``, ``Path(a, b)``, ``joinpath``, a name built on another line)
    gets past it. What it does not see: a constructor reached by ``getattr`` or a string; a
    receiver spelled as a ``_NOT_A_WORKSPACE`` entry that another module or an attribute
    assignment has pointed at a ``Workspace``; a ``Workspace`` handed on by an exempt file or
    by code outside ``crb``; and a ``git worktree add`` run as a subprocess (the lexical
    ratchet above covers the name)."""
    tree = ast.parse(source)
    ws = _workspace_names(tree)
    let_off = _let_off(tree)
    scopes: list[ast.AST] = [tree] + [n for n in ast.walk(tree) if isinstance(n, _SCOPES)]
    owns = {id(s): _own(s) for s in scopes}
    bindings = _scope_bindings(tree, scopes, owns)
    offenders: list[str] = []
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and id(n) not in called and _is_ctor(n, let_off):
            offenders.append(f"{rel}:{n.lineno}: {ast.unparse(n)[:120]} (as a value)")
    for v in _workspace_as_values(tree, ws):
        offenders.append(f"{rel}:{v.lineno}: {ast.unparse(v)[:120]} (Workspace as a value)")
    for scope in scopes:
        assigned = bindings[id(scope)]
        for n in owns[id(scope)]:
            if not isinstance(n, ast.Call):
                continue
            dest = _dest_arg(n, let_off)
            if dest is None:
                continue
            ok = _is_opaque(dest) or (
                isinstance(dest, ast.Name)
                and bool(assigned.get(dest.id))
                and all(v is not None and _is_opaque(v) for v in assigned[dest.id])
            )
            if not ok:
                offenders.append(f"{rel}:{n.lineno}: {ast.unparse(n)[:120]}")
    return offenders


def test_every_replay_side_worktree_is_named_by_opaque_dest() -> None:
    """The class, structurally: a new run kind that creates a worktree anywhere in ``crb``
    without ``opaque_dest`` fails here, however the path is spelled."""
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted((root / "src" / "crb").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in _DEST_EXEMPT:
            continue
        offenders += worktree_dest_offenders(path.read_text(encoding="utf-8"), rel)
    assert offenders == [], "worktrees not named by opaque_dest:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "body",
    [
        'Workspace.create(repo, sha, Path(scratch, f"run-{task.short_id}"), config=c)',
        'dest = scratch.joinpath(f"run-{sha[:10]}")\n    Workspace.create(repo, sha, dest)',
        'name = f"run-{sha[:10]}"\n    dest = scratch / name\n    Workspace.create(repo, sha, dest)',
        'dest = opaque_dest(scratch, "run")\n    dest = scratch / sha\n    Workspace.create(repo, sha, dest)',
        'Workspace.at_ref(repo, ref, dest=scratch / "fixed", config=c)',
        "repo.worktree_add(scratch / sha[:7], sha)",
        "Workspace.create(repo, sha, undefined_here)",
    ],
    ids=["path-ctor", "joinpath", "two-lines", "reassigned", "at-ref-kw", "worktree-add", "param"],
)
def test_the_structural_ratchet_catches_every_spelling(body: str) -> None:
    src = f"def f(repo, sha, scratch, task, c, ref, undefined_here=None):\n    {body}\n"
    assert len(worktree_dest_offenders(src, "x.py")) == 1


#: An opaque name first, then ``dest`` rebound by a construct that is not a plain assignment.
_OPAQUE_FIRST = 'dest = opaque_dest(scratch, "run")\n    '


@pytest.mark.parametrize(
    "body",
    [
        "with open(sha) as dest:\n        Workspace.create(repo, sha, dest)",
        "with ctx() as (dest, x):\n        Workspace.create(repo, sha, dest)",
        "dest, x = scratch / sha, 1\n    Workspace.create(repo, sha, dest)",
        "x, *dest = [scratch]\n    Workspace.create(repo, sha, dest)",
        "for dest, x in pairs:\n        Workspace.create(repo, sha, dest)",
        "try:\n        pass\n    except Exception as dest:\n"
        "        Workspace.create(repo, sha, dest)",
        "import os.path as dest\n    Workspace.create(repo, sha, dest)",
        "match sha:\n        case dest:\n            Workspace.create(repo, sha, dest)",
        "[Workspace.create(repo, sha, dest) for dest in pairs]",
    ],
    ids=[
        "with",
        "with-tuple",
        "tuple",
        "starred",
        "for-tuple",
        "except",
        "import",
        "match",
        "comp",
    ],
)
def test_the_structural_ratchet_sees_every_way_a_name_is_rebound(body: str) -> None:
    """PR #53 review: the ratchet read only ``=`` / ``:=`` / ``for`` bindings, so ``dest``
    rebound by ``with … as``, unpacking, ``except … as``, ``import … as``, a ``match``
    capture or a comprehension kept its earlier opaque assignment and passed. Every binding
    of a name counts; one that is not an ``opaque_dest(...)`` call makes the name suspect."""
    src = f"def f(repo, sha, scratch, pairs, ctx):\n    {_OPAQUE_FIRST}{body}\n"
    assert len(worktree_dest_offenders(src, "x.py")) == 1


def test_the_structural_ratchet_sees_async_rebinding_and_parameters() -> None:
    rebound = (
        "async def f(repo, sha, scratch, ctx, it):\n"
        f"    {_OPAQUE_FIRST}async with ctx() as dest:\n"
        "        Workspace.create(repo, sha, dest)\n"
        "    async for dest in it():\n"
        "        Workspace.create(repo, sha, dest)\n"
    )
    assert len(worktree_dest_offenders(rebound, "x.py")) == 2
    # a parameter is the caller's value until the body rebinds it: used first, it is suspect
    param = (
        "def f(repo, sha, scratch, dest):\n"
        "    Workspace.create(repo, sha, dest)\n"
        '    dest = opaque_dest(scratch, "run")\n'
    )
    assert len(worktree_dest_offenders(param, "x.py")) == 1


@pytest.mark.parametrize(
    "src",
    [
        # a nested function rebinds the enclosing ``dest`` through ``nonlocal``
        "def f(repo, sha, scratch):\n"
        '    dest = opaque_dest(scratch, "run")\n'
        "    def g():\n"
        "        nonlocal dest\n"
        "        dest = scratch / sha\n"
        "    g()\n"
        "    Workspace.create(repo, sha, dest)\n",
        # two levels down: the rebinding still reaches the scope that uses it
        "def f(repo, sha, scratch):\n"
        '    dest = opaque_dest(scratch, "run")\n'
        "    def g():\n"
        "        def h():\n"
        "            nonlocal dest\n"
        "            dest = scratch / sha\n"
        "        h()\n"
        "    g()\n"
        "    Workspace.create(repo, sha, dest)\n",
        # a function rebinds the module-level ``dest`` through ``global``
        'dest = opaque_dest(scratch, "run")\n'
        "def g():\n"
        "    global dest\n"
        "    dest = scratch / sha\n"
        "g()\n"
        "Workspace.create(repo, sha, dest)\n",
        # a name the scope itself declares ``global`` can be rebound by any other function
        "def f(repo, sha, scratch):\n"
        "    global dest\n"
        '    dest = opaque_dest(scratch, "run")\n'
        "    Workspace.create(repo, sha, dest)\n",
        # a lambda is a scope: its call is read, and its parameter is the caller's value
        "def f(repo, sha, scratch):\n    mk = lambda: Workspace.create(repo, sha, scratch / sha)\n",
        "def f(repo, sha, scratch):\n"
        "    mk = lambda dest=scratch / sha: Workspace.create(repo, sha, dest)\n",
        # a destination the ratchet cannot resolve is not a destination it can admit
        'Workspace.create(repo, sha, **{"dest": scratch / sha})\n',
        "Workspace.create(repo, *(sha, scratch / sha))\n",
        "Workspace.create(*args)\n",
        # the constructor reached by another name
        "from crb.core.workspace import Workspace as W\nW.create(repo, sha, scratch / sha)\n",
        "import crb.core.workspace as w\nw.Workspace.at_ref(repo, ref, scratch / ref)\n",
        # the constructor handed on as a value: its destination is out of sight
        "make = Workspace.create\nmake(repo, sha, scratch / sha)\n",
        "partial(repo.worktree_add, scratch / sha)(sha)\n",
        # a nested ``def`` rebinds the name as surely as ``=`` does
        "def f(repo, sha, scratch):\n"
        '    dest = opaque_dest(scratch, "run")\n'
        "    def dest(): ...\n"
        "    Workspace.create(repo, sha, dest)\n",
        # a class body is its own scope: its opaque ``dest`` is not the function's ``dest``
        "dest = scratch / sha\n"
        "def f(repo, sha, scratch):\n"
        "    class C:\n"
        '        dest = opaque_dest(scratch, "run")\n'
        "    Workspace.create(repo, sha, dest)\n",
    ],
    ids=[
        "nonlocal",
        "nonlocal-deep",
        "global-rebound",
        "global-declared",
        "lambda-call",
        "lambda-param",
        "double-star",
        "star",
        "star-only",
        "import-alias",
        "module-alias",
        "as-value",
        "partial",
        "def-rebind",
        "class-body",
    ],
)
def test_the_structural_ratchet_sees_other_scopes_and_other_names(src: str) -> None:
    """PR #53 review, second round: ``nonlocal`` / ``global`` rebinding from another
    function, a call inside a ``lambda``, a ``**`` / ``*`` destination and an aliased
    ``Workspace`` each passed with 0 offenders. Each must now give exactly one."""
    assert len(worktree_dest_offenders(src, "x.py")) == 1


@pytest.mark.parametrize(
    "src",
    [
        "W = Workspace\nW.create(repo, sha, scratch / sha)\n",
        "W: type[Workspace] = Workspace\nW.create(repo, sha, scratch / sha)\n",
        "(W := Workspace).create(repo, sha, scratch / sha)\n",
        "W, x = Workspace, 1\nW.create(repo, sha, scratch / sha)\n",
        "for W in [Workspace]:\n    W.create(repo, sha, scratch / sha)\n",
        "import crb.core.workspace as w\nW = w.Workspace\nW.create(repo, sha, scratch / sha)\n",
        "kinds = {'ws': Workspace}\nkinds['ws'].create(repo, sha, scratch / sha)\n",
        "def make():\n    return Workspace\nmake().create(repo, sha, scratch / sha)\n",
        "def build(W):\n    W.create(repo, sha, scratch / sha)\nbuild(Workspace)\n",
    ],
    ids=[
        "name-alias",
        "annotated",
        "walrus",
        "tuple",
        "for",
        "module-attr",
        "dict",
        "return",
        "argument",
    ],
)
def test_the_structural_ratchet_sees_workspace_handed_on_as_a_value(src: str) -> None:
    """PR #53 review, third round: the alias scan followed only ``W = Workspace``, so an
    annotated ``W: T = Workspace``, a walrus ``(W := Workspace)``, unpacking, a ``for``, a
    container, a return value or an argument each let ``W.create(…)`` through with 0
    offenders. Enumerating the ways to bind an alias was the gap, as it was for ``dest``;
    ``Workspace`` used as a value at all (not as ``Workspace.<attr>``, not as a type) is
    the class. Since the fourth round a ``create`` on any receiver counts too, so each
    spelling is named at both ends: exactly one ``Workspace`` as a value and exactly one
    call whose destination is not opaque."""
    found = worktree_dest_offenders(src, "x.py")
    values = [f for f in found if f.endswith("(Workspace as a value)")]
    assert len(values) == 1, found
    assert len(found) == 2 and "create(repo, sha, scratch / sha)" in "".join(found), found


@pytest.mark.parametrize(
    "src",
    [
        "def g(ws: Workspace, repo, sha, scratch):\n    return ws.create(repo, sha, scratch / sha)\n",
        "def g(ws, repo, sha, scratch):\n    return type(ws).create(repo, sha, scratch / sha)\n",
        "def g(ws, repo, ref, scratch):\n    return ws.__class__.at_ref(repo, ref, scratch / ref)\n",
        # a name on the allowlist that the file rebinds is no longer the listed class
        "from crb.builders.container import SealedCheckout\n"
        "SealedCheckout = pick()\n"
        "SealedCheckout.create(repo, sha, scratch / sha)\n",
        "def g(SealedCheckout, repo, sha, scratch):\n"
        "    SealedCheckout.create(repo, sha, scratch / sha)\n",
    ],
    ids=["instance", "type-of", "dunder-class", "allowlisted-rebound", "allowlisted-param"],
)
def test_the_structural_ratchet_reads_create_and_at_ref_on_any_receiver(src: str) -> None:
    """PR #53 review, fourth round: ``Workspace.create`` and ``Workspace.at_ref`` are
    classmethods, so an instance reaches them (``ws.create(…)``, ``type(ws).create(…)``)
    and gave 0 offenders. Following the receiver back to ``Workspace`` was the gap, as
    following the alias was; the attribute name is the class, as ``worktree_add`` already
    is, and only a receiver on ``_NOT_A_WORKSPACE`` that the file never rebinds is let off."""
    assert len(worktree_dest_offenders(src, "x.py")) == 1


@pytest.mark.parametrize(
    "src",
    [
        "from crb.core.workspace import Workspace as SealedCheckout\n"
        "SealedCheckout.create(repo, sha, scratch / sha)\n",
        "def f(repo, sha, scratch):\n"
        "    from crb.core.workspace import Workspace as SealedCheckout\n"
        "    SealedCheckout.create(repo, sha, scratch / sha)\n",
        "from somewhere import Other as SealedCheckout\n"
        "SealedCheckout.create(repo, sha, scratch / sha)\n",
    ],
    ids=["workspace-alias", "workspace-alias-in-function", "any-rename"],
)
def test_the_structural_ratchet_lets_off_only_a_name_imported_as_itself(src: str) -> None:
    """PR #53 review, fifth round: ``from … import Workspace as SealedCheckout`` bound an
    allowlisted name by ``from … import`` alone, so the ratchet let ``SealedCheckout.create``
    off and gave 0 offenders. A bare ``_NOT_A_WORKSPACE`` name is let off only when every
    import of it is that name under its own spelling; a rename makes it whatever was
    imported, so the call is read as a worktree constructor."""
    assert len(worktree_dest_offenders(src, "x.py")) == 1
    call = src.splitlines()[-1].strip()
    as_itself = f"from crb.builders.container import SealedCheckout\n{call}\n"
    assert worktree_dest_offenders(as_itself, "x.py") == []


@pytest.mark.parametrize(
    "src",
    [
        "Box[Workspace].create(repo, sha, scratch / sha)\n",
        "registry[Workspace].create(repo, sha, scratch / sha)\n",
    ],
    ids=["generic-looking", "runtime-index"],
)
def test_the_structural_ratchet_reads_a_subscript_index_as_a_type_only_for_a_generic(
    src: str,
) -> None:
    """PR #53 review, fourth round: every subscript index counted as a type, so
    ``Box[Workspace]`` handed ``Workspace`` on unseen. Only a known generic's index is a
    type now; here both the value and the call it reaches are named. Runtime indexing
    (``registry[Workspace]``) is the same case (fifth round)."""
    found = worktree_dest_offenders(src, "x.py")
    assert len(found) == 2
    assert sum("(Workspace as a value)" in f for f in found) == 1


def test_the_structural_ratchet_admits_workspace_as_a_type() -> None:
    """An annotation or a type expression names the class without handing it on, and a
    plain ``Workspace(…)`` wraps a directory that already exists: the replay-side modules
    do both and must stay clean."""
    src = (
        "from collections.abc import Callable\n"
        "BuildFn = Callable[[Workspace, str], None]\n"
        "Kinds = tuple[type[Workspace], ...]\n"
        "Opt = typing.Optional[Workspace]\n"
        "held: Workspace | None = None\n"
        "def f(ws: Workspace, repo, sha, scratch) -> Workspace:\n"
        '    return Workspace.create(repo, sha, opaque_dest(scratch, "run"))\n'
        "def wrap(repo, root) -> Workspace:\n"
        '    return Workspace(repo, root, sha="HEAD", parent="HEAD")\n'
    )
    assert worktree_dest_offenders(src, "x.py") == []


@pytest.mark.parametrize(
    "body",
    [
        'Workspace.create(repo, sha, opaque_dest(scratch, "run"), config=c)',
        'dest = opaque_dest(scratch, "mine", avoid=(sha,))\n    Workspace.create(repo, sha, dest)',
        'SealedCheckout.create(ws, scratch / "x", test_files=())',
        # ``nonlocal`` that keeps the name opaque is still admitted
        'dest = opaque_dest(scratch, "a")\n    def g():\n        nonlocal dest\n'
        '        dest = opaque_dest(scratch, "b")\n    g()\n    Workspace.create(repo, sha, dest)',
        # an explicit ``dest=`` beside ``**`` is resolvable
        'Workspace.create(repo, sha, dest=opaque_dest(scratch, "run"), **extra)',
        # the OpenAI SDK's ``create`` makes a chat completion, not a worktree
        "call = lambda: self.client.chat.completions.create(**kwargs)",
    ],
    ids=[
        "inline",
        "named",
        "not-a-worktree-constructor",
        "nonlocal-opaque",
        "kw-beside-star",
        "sdk-completion",
    ],
)
def test_the_structural_ratchet_admits_an_opaque_name(body: str) -> None:
    src = f"def f(repo, sha, scratch, c, ws):\n    {body}\n"
    assert worktree_dest_offenders(src, "x.py") == []
