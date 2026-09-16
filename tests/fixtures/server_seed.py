"""A small synthetic store for the domain-route tests, seeded THROUGH ``DbLedger``.

Shape (repo ``alpha`` unless noted):

* **deliver cell** ``replay|bug.fix|S|python|editblock|gpt-oss-120b|cerebras`` — 40 rows,
  38 clean (point 0.95, Wilson lower ≈ 0.835) → routes ``deliver``. Five of them
  belong to the ``succeeded`` run (T3 needs two attempts: ``r1`` red, ``r2`` clean).
* **thin cell** ``replay|backend.route.add|M|python|editblock|gpt-oss-120b|cerebras`` —
  3 graded rows (2 clean) plus the error row below → n = 4, ``calibrate`` (n < 10).
* **legacy cell** ``replay|test.add|XS|python|claude-code-workflow|sonnet|anthropic`` —
  6 census-style rows, ``belt_set="v3-legacy"``, ``source_changed=None``, apparatus
  ``1.0-census``, imported evidence packs hashed whole.
* one ``error`` row (harness failure, belts ``None``) on the ``failed`` run.
* a run per status (``queued``/``running``/``succeeded``/``failed``/``cancelled``) plus
  ``oracle``, ``controls`` and ``probe`` runs; StepEvents for the succeeded run, four
  ``oracle.score`` events and one ``controls.report``.
* repo ``beta`` (go): no rows, no tasks, no clone — the honest-empty case.

Every native row carries a real :class:`~crb.core.evidence.EvidencePack` whose grade
matches the row's belts, stored via ``DbLedger.store_pack``; ``append_many`` chains
the rows. Nothing here bypasses the write path — tests that need a false-Q1 row
insert one deliberately with the ORM and say so.

Navigation
----------
What it is:   The seeded store behind every domain-route test: a small synthetic ledger written
              THROUGH ``DbLedger``, users per role, and a logged-in test client.
What it does: Seeds repo ``alpha`` with a deliver cell (40 rows, 38 clean), a thin cell, a
              legacy census-style cell, one harness-error row, a run per status plus oracle,
              controls and probe runs with their events, and repo ``beta`` as the honest-empty
              case; every native row carries a real evidence pack whose grade matches its belts.
              Nothing bypasses the write path — a test that needs a false-Q1 row inserts one
              with the ORM deliberately and says so. ``assert_rbac`` pins 401/403/allowed per
              role ladder.
How:          ``make_env(role)`` builds settings and a SQLite file under ``tmp_path``, creates the
              app, seeds through ``DbLedger.append_many`` / ``store_pack``, inserts users with a
              cached argon2 hash and logs the client in; ``Env`` wraps GET/POST/PUT with the CSRF
              header.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/store/ledger.py (the write path every row goes through),
              src/crb/server/app.py (``create_app``), src/crb/server/auth.py (``hash_password``,
              the role ladder), tests/fixtures/signoff_seed.py (layers the sign-off helpers on
              top), tests/test_server_routes_capability.py and tests/test_server_routes_runs.py
              (typical consumers)
Tested by:    tests/test_server_routes_capability.py, tests/test_server_routes_runs.py,
              tests/test_server_routes_signoffs.py, tests/test_server_routes_ledger.py (every
              ``test_server_routes_*`` module)
Touch when:   a route needs a run status, event kind or cell shape the seed lacks (add it here
              and update every count the route tests assert — the seed's numbers are load-bearing:
              Wilson lower ≈ 0.835 on the deliver cell, n = 4 on the thin one); a column is added
              to ``GradeRow`` (``_result`` must still produce a pack whose grade matches).
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from crb.core.evidence import ApparatusStamp, BuilderRef, EvidencePack, canonical_json, sha256_text
from crb.core.grade import Belts, GradeResult
from crb.core.ledger import BELT_SET_V3_LEGACY, GradeRow, grade_row_from_result
from crb.core.spec import TaskSpec
from crb.observability.events import StepEvent, StepStatus
from crb.server.app import API_PREFIX, create_app
from crb.server.auth import hash_password
from crb.server.settings import Settings
from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.ledger import DbLedger
from crb.store.models import Event, Repo, Run, Task, User

ROOT_PW = "correct-horse-battery-staple"
USER_PW = "long-enough-password"
USERS: dict[str, str] = {
    "admin": "root",
    "viewer": "viewer1",
    "operator": "op1",
    "approver": "appr1",
}

ALPHA = "alpha"
BETA = "beta"

BUILDER = "editblock"
MODEL = "gpt-oss-120b"
PROVIDER = "cerebras"
LEGACY_BUILDER = "claude-code-workflow"
LEGACY_MODEL = "sonnet"
LEGACY_PROVIDER = "anthropic"
LEGACY_APPARATUS = "1.0-census"
LEGACY_PROVENANCE = "imported:expansion-bench-census-2026-07-08"

DELIVER_CELL: dict[str, str] = {
    "process_step": "replay",
    "capability_class": "bug.fix",
    "size": "S",
    "language": "python",
    "builder": BUILDER,
    "model": MODEL,
    "provider": PROVIDER,
}
THIN_CELL: dict[str, str] = {**DELIVER_CELL, "capability_class": "backend.route.add", "size": "M"}
LEGACY_CELL: dict[str, str] = {
    "process_step": "replay",
    "capability_class": "test.add",
    "size": "XS",
    "language": "python",
    "builder": LEGACY_BUILDER,
    "model": LEGACY_MODEL,
    "provider": LEGACY_PROVIDER,
}

RUN_IDS: dict[str, str] = {
    "queued": "a" * 32,
    "running": "b" * 32,
    "succeeded": "c" * 32,
    "failed": "d" * 32,
    "cancelled": "e" * 32,
    "oracle": "f" * 32,
    "controls": "0" * 32,
    "probe": "1" * 32,
}


def task_id(i: int) -> str:
    """A stable 40-hex task id for seed task ``i`` (sha1 of ``task-<i>``)."""
    return hashlib.sha1(f"task-{i}".encode()).hexdigest()


def _task(i: int, cls: str, size: str) -> TaskSpec:
    return TaskSpec(
        task_id=task_id(i),
        repo=ALPHA,
        subject=f"fix: task {i}",
        authored=f"2026-08-{i:02d}T12:00:00+00:00",
        test_files=(f"tests/test_t{i}.py",),
        src_files=(f"src/pkg/m{i}.py",),
        target_tests=(f"tests/test_t{i}.py",),
        belt_scope=("tests/",),
        pool="hard" if i == 6 else "standard",
        src_churn=12 if size == "S" else (60 if size == "M" else 3),
        size=size,
        capability_class=cls,
        language="python",
        baseline_failing=(f"tests/test_t{i}.py::test_x",),
        red_checked=True,
        gold_clean=None if i == 8 else True,
    )


def _result(task: TaskSpec, *, clean: bool, error: str = "") -> GradeResult:
    if error:
        belts = Belts()
    elif clean:
        belts = Belts(True, True, True, True)
    else:
        belts = Belts(True, False, True, True)
    return GradeResult(
        task_id=task.task_id,
        repo=task.repo,
        mode="sighted",
        clean=clean,
        belts=belts,
        error=error,
        note="" if clean else "target still red",
        duration_s=1.5,
    )


@dataclass
class SeedInfo:
    """What ``seed`` created: the tasks, the chained rows, their pack hashes, the run ids per
    status and the three cells the route tests address by name.
    """

    tasks: list[TaskSpec]
    rows: list[GradeRow] = field(default_factory=list)
    pack_hashes: list[str] = field(default_factory=list)
    run_ids: dict[str, str] = field(default_factory=dict)
    deliver_cell: dict[str, str] = field(default_factory=lambda: dict(DELIVER_CELL))
    thin_cell: dict[str, str] = field(default_factory=lambda: dict(THIN_CELL))
    legacy_cell: dict[str, str] = field(default_factory=lambda: dict(LEGACY_CELL))

    @property
    def succeeded_rows(self) -> list[GradeRow]:
        """The rows of the ``succeeded`` run (T3's ``r1`` red + ``r2`` clean among them)."""
        return [r for r in self.rows if r.run_id == RUN_IDS["succeeded"]]

    def task(self, i: int) -> TaskSpec:
        """Seed task ``i`` (1-based, the numbering the docstring uses)."""
        return self.tasks[i - 1]


# ---------------------------------------------------------------------------
# Store + settings + users
# ---------------------------------------------------------------------------


def make_factory(tmp_path: Path, name: str = "routes.db") -> sessionmaker[Session]:
    """A fresh SQLite database under ``tmp_path`` with every table and trigger installed."""
    engine = make_engine(f"sqlite:///{tmp_path / name}")
    init_db(engine)
    return make_session_factory(engine)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Dev ``Settings`` on ``tmp_path``: local sandbox, a fixed 40-char secret, the bootstrap admin
    the seed's users are keyed on; ``overrides`` win.
    """
    base: dict[str, Any] = {
        "env": "dev",
        "home": tmp_path,
        "secret_key": SecretStr("s" * 40),
        "sandbox": {"executor": "local"},
        "bootstrap_admin": {"username": USERS["admin"], "password": ROOT_PW},
        "log_format": "text",
    }
    base.update(overrides)
    return Settings(**base)


@functools.lru_cache(maxsize=2)
def _user_hash(password: str) -> str:
    return hash_password(password)


def add_users(factory: sessionmaker[Session]) -> None:
    """root (admin) / viewer1 / op1 / appr1, inserted directly with a cached argon2 hash.

    Seeding root here means the app's one-time bootstrap (which only runs on an EMPTY
    users table) is skipped — the fixture, not the environment, owns the accounts."""
    with factory() as s:
        for role, name in USERS.items():
            s.add(
                User(
                    id=hashlib.sha256(name.encode()).hexdigest()[:32],
                    subject=f"local:{name}",
                    issuer="local",
                    email=f"{name}@example.invalid",
                    display_name=name,
                    role=role,
                    password_hash=_user_hash(ROOT_PW if role == "admin" else USER_PW),
                )
            )
        s.commit()


def login(client: TestClient, role: str = "admin") -> None:
    """Log the client in as ``role`` and copy the CSRF cookie into the header every mutating
    request needs.
    """
    name = USERS[role]
    password = ROOT_PW if role == "admin" else USER_PW
    r = client.post(f"{API_PREFIX}/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = client.cookies["crb_csrf"]


def logout(client: TestClient) -> None:
    """Log out and forget the cookies and the CSRF header (the next call is anonymous)."""
    client.post(f"{API_PREFIX}/auth/logout")
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def _event(trace: str, seq: int, stage: str, action: str, **kw: Any) -> Event:
    payload = kw.pop("payload", {})
    ev = StepEvent(
        trace_id=trace,
        stage=stage,
        action=action,
        status=kw.pop("status", StepStatus.OK),
        repo=ALPHA,
        actor="worker-1",
        payload=payload,
        seq=seq,
        **kw,
    )
    d = ev.to_dict()
    p = d.pop("payload")
    return Event(**d, payload_json=p)


def seed(factory: sessionmaker[Session], *, clone_path: str = "") -> SeedInfo:
    """Populate ``factory`` with the store the docstring describes and return the ``SeedInfo``;
    ``clone_path`` sets ``alpha``'s clone (empty = never cloned).
    """
    tasks = [
        _task(1, "bug.fix", "S"),
        _task(2, "bug.fix", "S"),
        _task(3, "bug.fix", "S"),
        _task(4, "bug.fix", "S"),
        _task(5, "backend.route.add", "M"),
        _task(6, "backend.route.add", "M"),
        _task(7, "test.add", "XS"),
        _task(8, "test.add", "XS"),
    ]
    info = SeedInfo(tasks=tasks, run_ids=dict(RUN_IDS))
    ledger = DbLedger(factory)
    apparatus = ApparatusStamp(runner="pytest", executor={"kind": "local"})
    builder = BuilderRef(
        name=BUILDER, model=MODEL, provider=PROVIDER, cost_usd=0.012, latency_s=42.0, tokens_in=1000
    )

    rows: list[GradeRow] = []
    packs: list[EvidencePack] = []

    def native(task: TaskSpec, *, run_id: str, trial: str, clean: bool, error: str = "") -> None:
        result = _result(task, clean=clean, error=error)
        pack = EvidencePack(
            task=task,
            grade=result,
            apparatus=apparatus,
            builder=builder,
            run_id=run_id,
            trial=trial,
            actor="worker-1",
        )
        packs.append(pack)
        rows.append(
            grade_row_from_result(
                result,
                task,
                pack_hash=pack.pack_hash,
                builder=builder,
                run_id=run_id,
                trial=trial,
                actor="worker-1",
            )
        )

    # deliver cell — the succeeded run: T1 r1 ✓, T2 r1 ✓, T3 r1 ✗ + r2 ✓, T4 r1 ✓
    ok = RUN_IDS["succeeded"]
    native(tasks[0], run_id=ok, trial="r1", clean=True)
    native(tasks[1], run_id=ok, trial="r1", clean=True)
    native(tasks[2], run_id=ok, trial="r1", clean=False)
    native(tasks[2], run_id=ok, trial="r2", clean=True)
    native(tasks[3], run_id=ok, trial="r1", clean=True)
    # deliver cell — 35 historical rows (34 clean) → 40 rows, 38 clean
    for k in range(35):
        hist = hashlib.md5(f"hist-{k // 4}".encode()).hexdigest()
        native(tasks[k % 4], run_id=hist, trial="r1", clean=(k != 17))
    # thin cell — 3 rows, 2 clean
    thin = hashlib.md5(b"hist-thin").hexdigest()
    native(tasks[4], run_id=thin, trial="r1", clean=True)
    native(tasks[5], run_id=thin, trial="r1", clean=False)
    native(tasks[5], run_id=thin, trial="r2", clean=True)
    # the failed run — one harness error (fails closed)
    native(
        tasks[4],
        run_id=RUN_IDS["failed"],
        trial="r1",
        clean=False,
        error="SandboxUnavailable: docker daemon unreachable",
    )

    # legacy cell — 6 census-style rows (5 clean), imported packs hashed whole
    imported_packs: list[tuple[str, dict[str, Any], TaskSpec]] = []
    for k in range(6):
        task = tasks[6 + (k % 2)]
        clean = k != 5
        raw = {
            "repo": ALPHA,
            "task": task.task_id,
            "clean": clean,
            "tests_unmodified": True,
            "target_green": clean,
            "no_new_failures": True,
            "trial": f"c{k}",
        }
        pack = {
            "schema": "crb.evidence.imported.v1",
            "source": {"file": "grades.jsonl", "line": k + 1},
            "row": raw,
        }
        pack_hash = sha256_text(canonical_json(pack))
        imported_packs.append((pack_hash, pack, task))
        rows.append(
            GradeRow(
                repo=ALPHA,
                task_id=task.task_id,
                clean=clean,
                tests_unmodified=True,
                target_green=clean,
                no_new_failures=True,
                source_changed=None,
                capability_class=task.capability_class,
                size=task.size,
                language="python",
                pool=task.pool,
                mode="sighted",
                builder=LEGACY_BUILDER,
                model=LEGACY_MODEL,
                provider=LEGACY_PROVIDER,
                run_id="census-wave-1",
                trial=f"c{k}",
                actor="import",
                created="2026-07-08T00:00:00+00:00",
                gold_clean=task.gold_clean,
                evidence_pack_hash=pack_hash,
                apparatus_version=LEGACY_APPARATUS,
                belt_set=BELT_SET_V3_LEGACY,
                provenance=LEGACY_PROVENANCE,
                labels={"operation": "census"},
            )
        )

    with factory() as s:
        s.add(
            Repo(
                name=ALPHA,
                language="python",
                runner="pytest",
                clone_path=clone_path,
                url="https://example.invalid/alpha.git",
                config_json={
                    "name": ALPHA,
                    "language": "python",
                    "runner": "pytest",
                    "path": clone_path,
                    "url": "https://example.invalid/alpha.git",
                    "src_prefix": "src/",
                    "test_prefix": "tests/",
                    "ext": ".py",
                    "belt_scope": "AFFECTED_DIRS",
                    "probe": "tests/test_smoke.py",
                    "mining": {"log_n": 50},
                },
                probe_status="ok",
                probe_detail="pytest 8.3 on python 3.12",
            )
        )
        s.add(
            Repo(
                name=BETA,
                language="go",
                runner="go",
                clone_path="",
                url="",
                config_json={"name": BETA, "language": "go", "runner": "go"},
                probe_status="unknown",
            )
        )
        for t in tasks:
            s.add(
                Task(
                    repo=ALPHA,
                    task_id=t.task_id,
                    pool=t.pool,
                    size=t.size,
                    capability_class=t.capability_class,
                    language=t.language,
                    authored=t.authored,
                    subject=t.subject,
                    red_checked=t.red_checked,
                    gold_clean=t.gold_clean,
                    spec_json=t.to_dict(),
                )
            )
        s.add_all(_runs())
        s.add_all(_events(tasks))
        s.commit()

    for pack in packs:
        ledger.store_pack(pack)
    with factory() as s:
        from crb.store.models import EvidencePackRow

        for pack_hash, body, task in imported_packs:
            if s.get(EvidencePackRow, pack_hash) is None:
                s.add(
                    EvidencePackRow(
                        pack_hash=pack_hash,
                        repo=ALPHA,
                        task_id=task.task_id,
                        run_id="census-wave-1",
                        body_json=body,
                    )
                )
        s.commit()
    info.rows = ledger.append_many(rows)
    info.pack_hashes = [p.pack_hash for p in packs] + [h for h, _, _ in imported_packs]
    return info


def _runs() -> list[Run]:
    common = {
        "repo": ALPHA,
        "builder": BUILDER,
        "model": MODEL,
        "provider": PROVIDER,
        "actor": "op1",
    }
    return [
        Run(
            id=RUN_IDS["queued"],
            kind="mine",
            mode="sighted",
            status="queued",
            repo=ALPHA,
            actor="op1",
            params_json={
                "limit": 20,
                "pool": "standard",
                "executor": "local",
                "timeout": 600,
                "task_ids": [],
            },
            created="2026-09-01T10:00:00+00:00",
        ),
        Run(
            id=RUN_IDS["running"],
            kind="replay",
            status="running",
            ladder_json=["r1", "r2"],
            params_json={
                "limit": 8,
                "pool": "",
                "executor": "docker",
                "timeout": 900,
                "task_ids": [],
            },
            progress_done=2,
            progress_total=8,
            counts_json={
                "tasks": 2,
                "clean": 1,
                "disqualified": 0,
                "errors": 0,
                "first_pass_clean": 1,
                "rows": 3,
                "current_task_id": task_id(3),
            },
            worker_id="worker-1",
            heartbeat="2026-09-01T10:05:00+00:00",
            created="2026-09-01T10:01:00+00:00",
            started="2026-09-01T10:02:00+00:00",
            **common,
        ),
        Run(
            id=RUN_IDS["succeeded"],
            kind="replay",
            status="succeeded",
            ladder_json=["r1", "r2"],
            params_json={
                "limit": None,
                "pool": "",
                "executor": "local",
                "timeout": 600,
                "task_ids": [task_id(1), task_id(2), task_id(3), task_id(4)],
            },
            apparatus_json={
                "apparatus_version": "2.0",
                "runner": "pytest",
                "executor": {"kind": "local"},
            },
            counts_json={
                "tasks": 4,
                "clean": 4,
                "disqualified": 0,
                "errors": 0,
                "first_pass_clean": 3,
                "rows": 5,
                "duration_s": 210.5,
                "stopped_reason": "",
            },
            progress_done=4,
            progress_total=4,
            created="2026-08-30T09:00:00+00:00",
            started="2026-08-30T09:00:10+00:00",
            finished="2026-08-30T09:03:40+00:00",
            **common,
        ),
        Run(
            id=RUN_IDS["failed"],
            kind="replay",
            status="failed",
            error="SandboxUnavailable: docker daemon unreachable",
            progress_done=1,
            progress_total=2,
            created="2026-08-29T09:00:00+00:00",
            started="2026-08-29T09:00:10+00:00",
            finished="2026-08-29T09:00:20+00:00",
            **common,
        ),
        Run(
            id=RUN_IDS["cancelled"],
            kind="blind",
            mode="blind",
            status="cancelled",
            cancel_requested=True,
            created="2026-08-28T09:00:00+00:00",
            started="2026-08-28T09:00:10+00:00",
            finished="2026-08-28T09:01:00+00:00",
            **common,
        ),
        Run(
            id=RUN_IDS["oracle"],
            kind="oracle",
            status="succeeded",
            repo=ALPHA,
            actor="op1",
            created="2026-08-27T09:00:00+00:00",
            finished="2026-08-27T09:20:00+00:00",
        ),
        Run(
            id=RUN_IDS["controls"],
            kind="controls",
            status="succeeded",
            repo=ALPHA,
            actor="op1",
            created="2026-08-26T09:00:00+00:00",
            finished="2026-08-26T09:20:00+00:00",
        ),
        Run(
            id=RUN_IDS["probe"],
            kind="probe",
            status="succeeded",
            repo=ALPHA,
            actor="op1",
            created="2026-08-25T09:00:00+00:00",
            finished="2026-08-25T09:00:30+00:00",
        ),
    ]


def _events(tasks: list[TaskSpec]) -> list[Event]:
    ok = RUN_IDS["succeeded"]
    t1 = tasks[0].task_id
    out = [
        _event(ok, 1, "prep", "prep.start", task_id=t1, status=StepStatus.IN_PROGRESS),
        _event(ok, 2, "build", "build.done", task_id=t1, duration_ms=30_000, cost_usd=0.012),
        _event(
            ok,
            3,
            "grade",
            "grade.belt",
            task_id=t1,
            payload={"belt": "tests_unmodified", "value": True},
        ),
        _event(
            ok,
            4,
            "grade",
            "grade.belt",
            task_id=t1,
            payload={"belt": "target_green", "value": True},
        ),
        _event(
            ok,
            5,
            "ledger",
            "ledger.append",
            task_id=t1,
            payload={"clean": True, "token": "sk-live-abcdefghijklmnopqrstuvwxyz0123"},
        ),
        _event(ok, 6, "system", "run.done", payload={"tasks": 4, "clean": 4}),
    ]
    orc = RUN_IDS["oracle"]
    scores = [
        (tasks[0], 10, 9, 0.9),
        (tasks[1], 8, 4, 0.5),
        (tasks[2], 6, 2, 0.3333),
        (tasks[4], 0, 0, None),
    ]
    for i, (task, total, killed, strength) in enumerate(scores, start=1):
        out.append(
            _event(
                orc,
                i,
                "oracle",
                "oracle.score",
                task_id=task.task_id,
                payload={
                    "schema": "crb.oracle_strength.v1",
                    "task_id": task.task_id,
                    "capability_class": task.capability_class,
                    "size": task.size,
                    "total": total,
                    "killed": killed,
                    "errors": 0,
                    "oracle_strength": strength,
                    "note": ""
                    if total
                    else "no mutants generated for the changed region — not scoreable",
                    "provenance": {"apparatus_version": "2.0", "mutator": "python-ast"},
                },
            )
        )
    ctl = RUN_IDS["controls"]
    out.append(
        _event(
            ctl,
            1,
            "oracle",
            "controls.report",
            payload={
                "schema": "crb.negative_controls.v1",
                "apparatus": {"apparatus_version": "2.0"},
                "n_tasks": 2,
                "n_rows": 14,
                "violations": 0,
                "escapes": 1,
                "not_constructible": 2,
                "skipped": 0,
                "passed": True,
                "escape_rows": [
                    {
                        "task_id": tasks[0].task_id,
                        "repo": ALPHA,
                        "control": "hardcode_cheat",
                        "expected": "caught",
                        "observed": "clean",
                        "verdict": "ESCAPE",
                        "note": "literal asserts special-cased",
                        "duration_s": 3.2,
                    }
                ],
                "rows": [],
            },
        )
    )
    return out


# ---------------------------------------------------------------------------
# One-call environment for the route tests
# ---------------------------------------------------------------------------


@dataclass
class Env:
    """One seeded, logged-in test environment: the client, the session factory, the seed and the
    settings the app was built with.
    """

    client: TestClient
    factory: sessionmaker[Session]
    info: SeedInfo
    settings: Settings

    def get(self, path: str, **kw: Any) -> Any:
        """``GET`` under the API prefix."""
        return self.client.get(f"{API_PREFIX}{path}", **kw)

    def post(self, path: str, **kw: Any) -> Any:
        """``POST`` under the API prefix (the CSRF header was set at login)."""
        return self.client.post(f"{API_PREFIX}{path}", **kw)

    def put(self, path: str, **kw: Any) -> Any:
        """``PUT`` under the API prefix (the CSRF header was set at login)."""
        return self.client.put(f"{API_PREFIX}{path}", **kw)


@contextmanager
def make_env(tmp_path: Path, *, clone_path: str = "", role: str | None = "admin") -> Iterator[Env]:
    """Seeded SQLite + users + a running app; logged in as ``role`` (``None`` = anonymous)."""
    factory = make_factory(tmp_path)
    info = seed(factory, clone_path=clone_path)
    add_users(factory)
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, factory)) as client:
        if role is not None:
            login(client, role)
        yield Env(client=client, factory=factory, info=info, settings=settings)


def envelope(r: Any) -> dict[str, Any]:
    """The error envelope of a non-2xx response — asserts the ``{"error": {code, message,
    detail}}`` shape and returns the inner object.
    """
    body = r.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "detail"}
    return dict(body["error"])


def assert_rbac(env: Env, method: str, path: str, *, min_role: str, json: Any = None) -> None:
    """401 anonymous; 403 for every role below ``min_role``; not 401/403 at ``min_role``."""
    ladder = ["viewer", "operator", "approver", "admin"]
    logout(env.client)
    r = env.client.request(method, f"{API_PREFIX}{path}", json=json)
    assert r.status_code == 401, (path, r.text)
    assert envelope(r)["code"] == "unauthenticated"
    for role in ladder[: ladder.index(min_role)]:
        login(env.client, role)
        r = env.client.request(method, f"{API_PREFIX}{path}", json=json)
        assert r.status_code == 403, (path, role, r.text)
        assert envelope(r)["code"] == "forbidden"
        logout(env.client)
    login(env.client, min_role)
    r = env.client.request(method, f"{API_PREFIX}{path}", json=json)
    assert r.status_code not in (401, 403), (path, min_role, r.text)


__all__ = [
    "ALPHA",
    "BETA",
    "DELIVER_CELL",
    "LEGACY_CELL",
    "ROOT_PW",
    "RUN_IDS",
    "THIN_CELL",
    "USERS",
    "USER_PW",
    "Env",
    "SeedInfo",
    "add_users",
    "assert_rbac",
    "envelope",
    "login",
    "logout",
    "make_env",
    "make_factory",
    "make_settings",
    "seed",
    "task_id",
]
