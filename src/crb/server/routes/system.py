"""``/health``, ``/health/live``, ``/metrics``, ``/version`` — unauthenticated; bind to an
internal interface.

``/health`` (the DEEP probe — readiness) aggregates the observability probes with three
store-level checks:

* ``db``          — the database answers.
* ``migrations``  — the database's Alembic revision IS the code's head
  (:func:`crb.store.migrate.head_status_on`). ``down`` (503) when it is behind, ahead,
  empty or an older unversioned schema — a long-lived pod whose store drifted must leave
  the Service, and the go-live checklist may point here truthfully; the revisions are in
  the detail where applicable (an empty store has none). A ``create_all`` store whose
  schema equals the head (a ``crb serve`` without ``crb migrate``) is ``degraded``, not
  down: complete, but unstamped until ``crb migrate`` runs.
* ``append_only`` — the ledger triggers exist AND an ``UPDATE`` on ``grades`` is refused
  (:func:`crb.store.ledger.assert_append_only`). Missing triggers = ``down``.
* ``ledger``      — row count and ``false_q1`` computed in SQL with the same belt
  semantics as :func:`crb.core.ledger.false_q1_total`; any false-Q1 row = ``down``.
  The same numbers refresh the ``crb_false_q1_total`` / ``crb_ledger_rows`` gauges.
* ``worker``      — liveness from the ``workers`` table each worker upserts every
  ``heartbeat_s`` even when idle (J-TEL-2): a worker seen within 3 × its own
  ``heartbeat_s`` is alive. ``degraded`` (never ``down``) when runs are queued and no
  worker is alive — nothing will start, and the sentence says so with the queue depth
  and the last check-in; when no worker has checked in yet; when one stopped checking
  in (named, with its age); when a running run's ``heartbeat`` is older than
  ``worker_heartbeat_stale_s``; or when a worker's row says it is still reaping a
  container whose ``docker kill`` the daemon never confirmed (``unconfirmed_containers``
  > 0 — src/crb/server/reaper.py; the container may still be running on that host);
  ``ok`` otherwise with the workers listed. The worker is
  a dependency the API pod does not own: ``/health`` is the API's readiness probe, and a
  503 for a crashed worker would take every API pod out of the Service — exactly when
  the person needs to read "no worker has checked in" (the same rule as the sandbox
  probe for the ``api`` role). Before the table existed the probe read running runs'
  heartbeats only, so a crashed worker with three queued runs answered ``ok "idle, 3
  queued"``.
* ``sandbox``     — the docker daemon answers (``docker`` executor) — **role-aware**:
  the sandbox is the WORKER's instrument. A process whose role is ``api`` (the
  ``serve`` container: no docker socket, by design — see ``deploy/Dockerfile``)
  reports the probe ``skipped``, never ``degraded``/``down``: a missing socket there
  is the intended posture, not a fault, and must not fail the API's health. The
  role is read from ``CRB_ROLE`` (:func:`process_role`; ``api`` | ``worker`` |
  ``all``, default ``all`` = one process does both, so everything is probed).

**A probe whose read raises never serves the exception.** Every read — the five store
probes here and the observability probes — runs under :func:`probes.run_probe`: the
result is ``down`` with the one fixed detail ``<probe> could not be read — see the API
log, request id <id>`` and empty ``data``, and the exception goes to the log under that
request id (CWE-209 — the route is unauthenticated, and a driver's message can carry a
DSN, a host, a user, a path or SQL). The route passes the id the middleware assigned
(``X-Request-ID``) so the sentence names the log line to look for.

``/health/live`` (LIVENESS) answers "this process is up and can reach its database"
and nothing else — never the sandbox, the toolchains, the builders or the ledger.
It is what the image ``HEALTHCHECK`` and the Helm liveness probe hit: a liveness
probe that fails on a *dependency* (a docker socket the API is not meant to have, a
transient builder outage) restarts a healthy process.

``status`` is ``down`` → HTTP 503 so a load balancer can act on it; ``degraded``
still answers 200 (the instrument can measure, with caveats); ``skipped`` is neither
(a probe this role does not own) and never lowers the aggregate.

Navigation
----------
What it is:   The ``/health``, ``/health/live``, ``/metrics`` and ``/version`` routes — the
              unauthenticated operational surface.
What it does: Readiness aggregates the store probes (db, migrations at head, append-only
              triggers proven live, ledger false-Q1 = 0, worker check-ins from the ``workers``
              table) with the
              observability probes
              (sandbox — skipped for the ``api`` role — toolchains, builders) and answers
              503 when any is ``down``; a read that raises is ``down`` with the fixed
              ``failure_detail`` naming the request id, the exception logged, never served;
              liveness checks the database only; ``/metrics``
              refreshes the ledger gauges then renders the shared registry.
How:          ``collect_health`` = the probe list, each under ``probes.run_probe`` with the
              request id → ``probes.aggregate`` → stamp;
              ``migrations_result`` turns a ``HeadStatus`` into the probe (``crb doctor``
              renders the same function from a bare URL);
              ``ledger_counts`` is the SQL twin of ``false_q1_total`` over the stored
              belts; ``process_role`` reads ``CRB_ROLE`` so the API container never fails
              on the docker socket it is not meant to have.
Layer:        server — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0011-repo-lint-belt.md (belt 5 in the false-Q1 predicate)
Works with:   src/crb/observability/probes.py (the probe vocabulary, ``run_probe`` /
              ``failure_detail`` and ``aggregate``),
              src/crb/store/migrate.py (``head_status_on`` — the one head check),
              src/crb/cli/commands/service.py (``crb doctor`` renders ``migrations_result``
              and ``probe_worker``),
              src/crb/store/ledger.py (``assert_append_only``), src/crb/observability/metrics.py
              (the gauges and the registry — the API's series only; the worker serves its
              own, docs/DEPLOYMENT.md#9-observability), src/crb/server/worker.py (upserts
              the ``workers`` rows the worker probe reads), src/crb/server/routes/signoffs.py
              (the same false-Q1 predicate, kept in step), deploy/entrypoint.sh + deploy/Dockerfile
              (``CRB_ROLE`` per container and the ``HEALTHCHECK`` on ``/health/live``),
              docs/API.md#health--metrics-no-auth-bind-to-an-internal-interface (the
              ``migrations`` contract the other documents copy)
Tested by:    tests/test_server_system.py, tests/test_deploy_health_probes.py
Touch when:   never for a new repository; adding a probe means deciding which role owns it
              (``skipped`` elsewhere), whether it may fail readiness, and putting its read
              under ``probes.run_probe`` (never an exception in a ``detail``); a new belt means
              extending the predicate here AND in ``FALSE_Q1_PREDICATE`` (signoffs.py) AND
              ``false_q1_total`` in src/crb/core/ledger.py together.
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import BELT_SET_V3_LEGACY, BELT_SET_V5, LedgerIntegrityError
from crb.core.routing import POLICY_VERSION
from crb.core.secrets_file import SecretsError
from crb.core.version import APPARATUS_VERSION, __version__
from crb.intake.client import STOP_ADVICE, TRACKER_TOKEN_SECRET
from crb.observability import metrics, probes
from crb.observability.probes import DEGRADED, DOWN, OK, ProbeResult
from crb.provision.probe import probe_provision
from crb.server.deps import ApiError, ErrorEnvelope, SessionFactoryDep, SettingsDep, request_id
from crb.server.intake import IntakeStore, ListenerState, needs_credential
from crb.server.secrets import SecretsFile
from crb.server.settings import Settings
from crb.store.ledger import assert_append_only
from crb.store.migrate import HeadStatus, head_status_on
from crb.store.models import APPEND_ONLY_TABLES, Grade, Repo, Run, User, WorkerRow

try:  # pragma: no cover — extra installed in [server]
    from prometheus_client import CONTENT_TYPE_LATEST
except ImportError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

router = APIRouter(tags=["system"])
_ERR = {"model": ErrorEnvelope}

#: A probe this process's role does not own — neither a pass nor a fault. Extends the
#: ``ok | degraded | down`` vocabulary of :mod:`crb.observability.probes` (its proper
#: home; that module is outside this change's file set — see the finish report).
#: :func:`probes.aggregate` lowers the aggregate only for ``degraded`` / ``down``.
SKIPPED = "skipped"

#: Process roles. ``api`` = the ``serve`` container (HTTP, no docker socket); ``worker``
#: = the queue consumer (owns the sandbox); ``all`` = one process does both.
ROLE_API = "api"
ROLE_WORKER = "worker"
ROLE_ALL = "all"
ROLES: tuple[str, ...] = (ROLE_API, ROLE_WORKER, ROLE_ALL)
#: With no ``CRB_ROLE`` the process assumes it does everything, so EVERY probe is
#: evaluated: an unset or unrecognised role never hides a probe (fail closed).
DEFAULT_ROLE = ROLE_ALL
ROLE_ENV = "CRB_ROLE"


def process_role(environ: Mapping[str, str] | None = None) -> str:
    """The role this process runs as, from ``CRB_ROLE`` (``api`` | ``worker`` | ``all``;
    case-insensitive; default and fallback for anything else: ``all``).

    Read here, once, rather than through :class:`Settings`: ``settings.py`` is the
    proper home for the field (reported as a follow-up); the documented contract is
    this function's, and the Helm chart / compose set the variable per container.
    """
    raw = (os.environ if environ is None else environ).get(ROLE_ENV, DEFAULT_ROLE)
    role = str(raw or "").strip().lower()
    return role if role in ROLES else DEFAULT_ROLE


# --- store-level probes -------------------------------------------------------------


def probe_db(factory: sessionmaker[Session], *, request_id: str = "") -> ProbeResult:
    """``db``: the database answers ``SELECT 1`` (plus the user count as a data point)."""

    def _read() -> ProbeResult:
        with factory() as s:
            s.execute(text("SELECT 1"))
            users = int(s.execute(select(func.count(User.id))).scalar_one())
            return ProbeResult(
                "db", OK, "ok", {"dialect": s.get_bind().dialect.name, "users": users}
            )

    return probes.run_probe("db", _read, request_id=request_id)


#: The fix every not-at-head reading names (the entrypoint / Helm Job runs the same command).
MIGRATE_FIX = "run `crb migrate` (the migrate Job / `python -m crb.store.migrate upgrade`)"


def migrations_result(st: HeadStatus) -> ProbeResult:
    """``migrations`` from a :class:`HeadStatus` — shared with ``crb doctor`` so the two
    surfaces cannot disagree. ``ok`` at head; ``degraded`` for a ``create_all`` schema that
    equals the head but carries no ``alembic_version`` (complete; ``crb migrate`` stamps it);
    ``down`` otherwise — behind, ahead, empty or an older unversioned schema — naming the
    revisions where applicable and the fix."""
    data = st.to_dict()
    if st.at_head:
        return ProbeResult("migrations", OK, f"database at {st.head} = code head", data)
    if st.database is not None:
        return ProbeResult(
            "migrations",
            DOWN,
            f"database at {st.database}, code head {st.head} — {MIGRATE_FIX}",
            data,
        )
    if st.matches_models:
        return ProbeResult(
            "migrations",
            DEGRADED,
            f"schema matches head {st.head} but carries no alembic_version (a create_all "
            "store) — run `crb migrate` to stamp it",
            data,
        )
    where = "empty" if st.unversioned_at is None else f"unversioned schema at {st.unversioned_at}"
    return ProbeResult(
        "migrations",
        DOWN,
        f"database not migrated ({where}), code head {st.head} — {MIGRATE_FIX}",
        data,
    )


def probe_migrations(factory: sessionmaker[Session], *, request_id: str = "") -> ProbeResult:
    """``migrations``: the store's Alembic revision against the packaged head, read on a
    session's own connection (one ``SELECT`` on ``alembic_version`` for a versioned store).
    A read that raises is ``down`` with the fixed ``failure_detail`` (``run_probe``)."""

    def _read() -> ProbeResult:
        with factory() as s:
            return migrations_result(head_status_on(s.connection()))

    return probes.run_probe("migrations", _read, request_id=request_id)


def _count_triggers(s: Session) -> int:
    """How many of the expected ``<table>_no_update`` / ``_no_delete`` triggers exist."""
    dialect = s.get_bind().dialect.name
    names = [f"{t}_{kind}" for t in APPEND_ONLY_TABLES for kind in ("no_update", "no_delete")]
    if dialect == "sqlite":
        rows = s.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars()
    elif dialect == "postgresql":
        rows = s.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars()
    else:  # pragma: no cover — unsupported by policy
        return 0
    present = set(rows)
    return sum(1 for n in names if n in present)


def probe_append_only(factory: sessionmaker[Session], *, request_id: str = "") -> ProbeResult:
    """``append_only``: every trigger present AND an UPDATE on ``grades`` refused —
    counting alone would pass a trigger that exists but does not fire. An accepted UPDATE
    is ``down`` in the ledger's own words (:class:`LedgerIntegrityError` names no
    secret); a read that raises is ``down`` with the fixed ``failure_detail``."""
    expected = 2 * len(APPEND_ONLY_TABLES)

    def _read() -> ProbeResult:
        with factory() as s:
            found = _count_triggers(s)
        data = {"triggers": found, "expected": expected}
        try:
            assert_append_only(factory)
        except LedgerIntegrityError as exc:
            return ProbeResult("append_only", DOWN, str(exc), data)
        if found < expected:
            return ProbeResult(
                "append_only", DOWN, f"{found}/{expected} append-only triggers present", data
            )
        return ProbeResult("append_only", OK, "triggers present; UPDATE on grades refused", data)

    return probes.run_probe("append_only", _read, request_id=request_id)


def ledger_counts(factory: sessionmaker[Session]) -> tuple[int, int]:
    """``(rows, false_q1)`` — a clean row whose recorded belts are not all True is false-Q1
    (belt 5 counts only where recorded — ``v5`` — and only when it rejected: ``NULL``
    there is *not evaluated*, ADR-0011)."""
    not_all_true = or_(
        Grade.tests_unmodified.is_not(True),
        Grade.target_green.is_not(True),
        Grade.no_new_failures.is_not(True),
        (Grade.belt_set != BELT_SET_V3_LEGACY) & Grade.source_changed.is_not(True),
        (Grade.belt_set == BELT_SET_V5) & Grade.repo_lint_clean.is_(False),
    )
    with factory() as s:
        rows = int(s.execute(select(func.count(Grade.seq))).scalar_one())
        fq1 = int(
            s.execute(
                select(func.count(Grade.seq)).where(Grade.clean.is_(True), not_all_true)
            ).scalar_one()
        )
    return rows, fq1


def refresh_ledger_gauges(factory: sessionmaker[Session]) -> tuple[int, int]:
    """Recount and push ``crb_ledger_rows`` / ``crb_false_q1_total``; returns the pair."""
    rows, fq1 = ledger_counts(factory)
    metrics.set_ledger_health(rows=rows, false_q1=fq1)
    return rows, fq1


def probe_ledger(factory: sessionmaker[Session], *, request_id: str = "") -> ProbeResult:
    """``ledger``: ``down`` on any false-Q1 row — the honesty floor is a readiness condition."""

    def _read() -> ProbeResult:
        rows, fq1 = refresh_ledger_gauges(factory)
        data = {"rows": rows, "false_q1": fq1}
        if fq1:
            return ProbeResult("ledger", DOWN, f"false_q1={fq1} — honesty floor breached", data)
        return ProbeResult("ledger", OK, f"{rows} rows, false_q1=0", data)

    return probes.run_probe("ledger", _read, request_id=request_id)


def _parse_ts(value: str) -> _dt.datetime | None:
    """ISO-8601 → aware UTC datetime, ``None`` when unparseable (treated as stale)."""
    try:
        ts = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.UTC)


#: A worker is alive when its last check-in is within this many of ITS OWN ``heartbeat_s``.
WORKER_ALIVE_HEARTBEATS = 3
#: A stopped worker row older than this is history: dropped from the listing. A lapsed
#: (not stopped) row is always listed — a crashed worker is a fact until it comes back.
WORKER_FORGET_AFTER_S = 3600


def _age_s(stamp: str, now: _dt.datetime) -> float | None:
    ts = _parse_ts(stamp) if stamp else None
    return None if ts is None else round((now - ts).total_seconds(), 1)


def _worker_view(row: WorkerRow, now: _dt.datetime) -> dict[str, Any]:
    """One worker for ``data.workers`` (and the UI): its check-in age against the
    staleness it promised, whether it is alive, what it holds, and a clean stop."""
    age = _age_s(row.heartbeat, now)
    stale_after = float(row.heartbeat_s or 0) * WORKER_ALIVE_HEARTBEATS
    alive = not row.stopped and age is not None and stale_after > 0 and age <= stale_after
    return {
        "worker_id": row.worker_id,
        "hostname": row.hostname,
        "executor": row.executor,
        "kinds": list(row.kinds or []),
        "started": row.started or None,
        "heartbeat": row.heartbeat or None,
        "heartbeat_age_s": age,
        "stale_after_s": stale_after,
        "current_run_id": row.current_run_id or None,
        "version": row.version,
        "stopped": row.stopped or None,
        "alive": alive,
        "unconfirmed_containers": int(row.unconfirmed_containers or 0),
    }


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def probe_worker(
    factory: sessionmaker[Session], stale_s: int, *, request_id: str = ""
) -> ProbeResult:
    """``worker`` (J-TEL-2): liveness from the ``workers`` table (every worker checks in
    every ``heartbeat_s``, idle or not), plus running runs' heartbeats.

    ``degraded``: runs are queued and no worker is alive (nothing will start — said with
    the queue depth and the last check-in, or the last clean stop); no worker has ever
    checked in; a worker stopped checking in (named, with its age); a running run's
    heartbeat is older than ``stale_s`` (the queue will reclaim it; the probe is the early
    warning); or a worker is still reaping containers whose kill went unconfirmed
    (``unconfirmed_containers`` summed over the listed workers — each may still be
    running). ``ok`` otherwise, naming the workers. Never ``down``: the API pod's readiness
    is not the worker's liveness (module docstring) — ``down`` is reserved for the store
    not answering, and then only through ``probes.run_probe`` (the fixed detail; the
    exception in the log, never served).
    """
    now = _dt.datetime.now(_dt.UTC)

    def _read() -> ProbeResult:
        with factory() as s:
            running = list(
                s.execute(
                    select(Run.id, Run.worker_id, Run.heartbeat).where(Run.status == "running")
                ).all()
            )
            queued = int(
                s.execute(select(func.count(Run.id)).where(Run.status == "queued")).scalar_one()
            )
            rows = list(s.execute(select(WorkerRow).order_by(WorkerRow.worker_id)).scalars())
        workers = [
            _worker_view(r, now)
            for r in rows
            if not r.stopped or (_age_s(r.heartbeat, now) or 0.0) <= WORKER_FORGET_AFTER_S
        ]
        alive = [w for w in workers if w["alive"]]
        stale_runs: list[str] = []
        for run_id, _worker, heartbeat in running:
            ts = _parse_ts(heartbeat) if heartbeat else None
            if ts is None or (now - ts).total_seconds() > stale_s:
                stale_runs.append(str(run_id))
        # the contract docs/API.md#health documents and ui/src/api/types.ts types (WorkerProbeData):
        # the top-level ``stale_after_s`` is the RUN threshold behind ``stale``; each worker's own
        # ``stale_after_s`` (3 × its heartbeat_s) is the bound behind its ``alive``
        unconfirmed = sum(int(w["unconfirmed_containers"]) for w in workers)
        data = {
            "workers": workers,
            "alive": len(alive),
            "running": len(running),
            "queued": queued,
            "stale": stale_runs,
            "stale_after_s": stale_s,
            "unconfirmed_containers": unconfirmed,
        }
        # a worker that should be alive and is not: not stopped, last seen too long ago
        lapsed = [w for w in workers if not w["alive"] and not w["stopped"]]
        if queued and not alive:
            stopped = [w for w in workers if w["stopped"]]
            if lapsed:
                recent = min(lapsed, key=lambda w: w["heartbeat_age_s"] or float("inf"))
                since = f"no worker has checked in for {recent['heartbeat_age_s'] or 0:.0f} s"
                since += f" ({recent['worker_id']})"
            elif stopped:
                last = min(stopped, key=lambda w: _age_s(w["stopped"], now) or float("inf"))
                since = (
                    f"the last worker ({last['worker_id']}) stopped "
                    f"{_age_s(last['stopped'], now) or 0:.0f} s ago"
                )
            else:
                since = "no worker has checked in yet"
            return ProbeResult(
                "worker",
                DEGRADED,
                f"{_plural(queued, 'run')} queued, {since} — queued runs will not start until "
                "a worker does",
                data,
            )
        if stale_runs:
            return ProbeResult(
                "worker", DEGRADED, f"{len(stale_runs)} running run(s) with a stale heartbeat", data
            )
        if lapsed:
            w = lapsed[0]
            return ProbeResult(
                "worker",
                DEGRADED,
                f"worker {w['worker_id']} last checked in {w['heartbeat_age_s'] or 0:.0f} s ago "
                f"(alive within {w['stale_after_s']:.0f} s)",
                data,
            )
        if not alive:
            return ProbeResult(
                "worker",
                DEGRADED,
                "no worker has checked in yet — queued runs will not start",
                data,
            )
        if unconfirmed:
            reaping = [w for w in workers if w["unconfirmed_containers"]]
            who = ", ".join(str(w["worker_id"]) for w in reaping)
            return ProbeResult(
                "worker",
                DEGRADED,
                f"{_plural(unconfirmed, 'container')} whose docker kill was not confirmed "
                f"{'are' if unconfirmed != 1 else 'is'} being reaped by worker {who} — each may "
                "still be running on its host; `docker ps` there names them and "
                "`docker rm -f <name>` reaps one by hand",
                data,
            )
        newest = min(alive, key=lambda w: w["heartbeat_age_s"] or 0.0)
        detail = (
            f"{_plural(len(alive), 'worker')}, last check-in {newest['heartbeat_age_s']:.0f} s ago"
        )
        if running:
            detail += f" · {_plural(len(running), 'run')} running"
        detail += f" · {_plural(queued, 'run')} queued"
        return ProbeResult("worker", OK, detail, data)

    return probes.run_probe("worker", _read, request_id=request_id)


def probe_sandbox(settings: Settings, role: str = ROLE_ALL, *, request_id: str = "") -> ProbeResult:
    """The sandbox executor, as seen from a process of ``role``.

    The sandbox belongs to the worker. An ``api`` process reports ``skipped``: the
    ``serve`` container carries the docker CLIENT only and no socket — by design
    (``deploy/Dockerfile``, ``docs/SECURITY.md``) — so probing the daemon there would
    always read ``down`` and take the API with it. ``worker`` / ``all`` probe it.
    """
    executor = settings.sandbox.executor
    if role == ROLE_API:
        return ProbeResult(
            "sandbox",
            SKIPPED,
            "not probed here: the sandbox is the worker's — this process is the API "
            f"({ROLE_ENV}={ROLE_API})",
            {"executor": executor, "role": role},
        )
    if executor == "docker":
        return probes.probe_docker(timeout=5, request_id=request_id)
    return ProbeResult(
        "sandbox",
        DEGRADED,
        "local executor — test runs are NOT isolated (dev only)",
        {"executor": "local"},
    )


#: How long ``/health`` reuses a worker's provisioning probe: it inspects three images and
#: a network and starts a container, which a readiness poll every few seconds must not do
#: each time (CodeRabbit on PR #56). A result that is not ``ok`` is reused for less, so a
#: fixed store is seen soon; ``crb doctor`` always probes afresh.
PROVISION_PROBE_TTL_S = 300.0
PROVISION_PROBE_DOWN_TTL_S = 30.0
_monotonic = time.monotonic
_provision_cache: dict[str, tuple[float, ProbeResult]] = {}
_provision_lock = threading.Lock()


def probe_provision_role(settings: Settings, role: str = ROLE_ALL) -> ProbeResult:
    """Dependency provisioning (ADR-0019), as seen from a process of ``role``: the worker
    fetches, so an ``api`` process reports ``skipped``; a worker reports ``skipped`` when
    provisioning is off, otherwise whether the store is visible to the daemon and the fetch
    images and the egress network are present (``crb.provision.probe``) — reused for
    :data:`PROVISION_PROBE_TTL_S` (``ok``) or :data:`PROVISION_PROBE_DOWN_TTL_S` (anything
    else) per configuration."""
    if role == ROLE_API:
        return ProbeResult(
            "provision",
            SKIPPED,
            f"not probed here: provisioning is the worker's ({ROLE_ENV}={ROLE_API})",
            {"enabled": settings.provision.enabled, "role": role},
        )
    config = settings.provision_config
    if not config.enabled:
        return probe_provision(config)
    key = repr(sorted(config.view().items(), key=lambda kv: kv[0]))
    now = _monotonic()
    with _provision_lock:
        hit = _provision_cache.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    result = probe_provision(config)
    ttl = PROVISION_PROBE_TTL_S if result.status == OK else PROVISION_PROBE_DOWN_TTL_S
    with _provision_lock:
        _provision_cache[key] = (now + ttl, result)
    return result


def probe_intake(
    factory: sessionmaker[Session], settings: Settings, *, request_id: str = ""
) -> ProbeResult:
    """``intake``: is work able to arrive from the enterprise's board (ADR-0017)?

    **It contacts no tracker.** A readiness probe that called somebody else's service would
    make this deployment's health depend on theirs, and would poll a board nobody asked it
    to. It reports what this deployment already knows about itself: whether a tracker is
    configured, whether a credential is stored, this deployment's own public address (a
    link on a ticket needs it), how many repositories have their listener switched on —
    **and the stop the last pass of each switched-on listener recorded on disk**.

    That last one needs no tracker contact and is the whole point of the line: a
    deployment whose every listener is failing ``unauthorised`` must not read ``ok``, or
    monitoring never learns the front door is shut. It reports ``degraded`` naming the
    repository, the published reason and the advice; the reachability it reports is
    therefore the reachability the last real poll MEASURED, not one this probe provoked.
    """

    def _read() -> ProbeResult:
        cfg = settings.intake
        # the store is read FIRST and unconditionally: how many listeners are on is part of
        # this probe's answer whatever the tracker setting says, and a store that cannot be
        # read must fail this probe like every other one rather than pass on a skip
        listening = 0
        stopped: list[tuple[str, str, str]] = []  # repo, reason, detail
        with factory() as session:
            for row in session.execute(select(Repo)).scalars().all():
                if not ListenerState.from_config(dict(row.config_json or {})).enabled:
                    continue
                listening += 1
                last = IntakeStore(settings.home, str(row.name)).last_poll() or {}
                reason = str(last.get("stopped") or "")
                if reason:
                    stopped.append((str(row.name), reason, str(last.get("detail") or "")))
        if cfg.tracker == "none":
            detail = (
                "no tracker configured (optional) — set CRB_INTAKE__TRACKER, __URL, __PROJECT "
                "and __COLUMN to take work from a board "
                "(docs/adr/0017-the-ticket-is-the-backlog-item.md)"
            )
            data = {"tracker": "none", "configured": False, "listening": listening}
            if listening:
                return ProbeResult(
                    "intake",
                    DEGRADED,
                    f"{listening} repository listener(s) are on but no tracker is configured — "
                    "nothing is read; set the CRB_INTAKE__* block or switch them off",
                    data,
                )
            return ProbeResult("intake", SKIPPED, detail, data)
        secrets_present = False
        try:
            secrets_present = bool(
                SecretsFile.for_settings(settings).status(TRACKER_TOKEN_SECRET).present
            )
        except (SecretsError, OSError):
            secrets_present = False
        data = {
            "tracker": cfg.tracker,
            "configured": cfg.enabled,
            "column": cfg.column,
            "credential_set": secrets_present,
            "public_url_set": bool(settings.public_url),
            "listening": listening,
            "poll_s": cfg.poll_s,
            "max_per_poll": cfg.max_per_poll,
            "stopped": [
                {"repo": r, "reason": reason, "detail": detail} for r, reason, detail in stopped
            ],
        }
        if not cfg.enabled:
            return ProbeResult(
                "intake",
                DEGRADED,
                f"tracker {cfg.tracker!r} is named but incomplete — CRB_INTAKE__URL and "
                "CRB_INTAKE__COLUMN are both required",
                data,
            )
        # The rule the consent gate and ``build_tracker`` apply, asked of the one function
        # that owns it: the walkthrough's file-backed board needs no credential, so a probe
        # that demanded one reported `degraded` — and told an admin to set a token — over a
        # poll that was succeeding.
        if needs_credential(cfg.tracker) and not secrets_present:
            return ProbeResult(
                "intake",
                DEGRADED,
                "no tracker credential stored — an admin sets it at "
                "PUT /settings/secrets/tracker-token; nothing can be read until they do",
                data,
            )
        if not settings.public_url:
            return ProbeResult(
                "intake",
                DEGRADED,
                "no CRB_PUBLIC_URL is set — a link this product writes on a ticket would be "
                "a relative path nobody on the tracker can open, so no listener may be "
                "switched on",
                data,
            )
        if listening == 0:
            return ProbeResult(
                "intake",
                OK,
                f"{cfg.tracker} configured; no repository has its listener switched on "
                "(the default) — nothing is read or written",
                data,
            )
        if stopped:
            worst = stopped[0]
            more = f" (and {len(stopped) - 1} more)" if len(stopped) > 1 else ""
            return ProbeResult(
                "intake",
                DEGRADED,
                f"the last read of {worst[0]!r} stopped: {worst[1]} — "
                f"{STOP_ADVICE.get(worst[1], 'see the intake screen for what to do')}{more}",
                data,
            )
        return ProbeResult(
            "intake",
            OK,
            f"{cfg.tracker} configured; {listening} repository listener(s) on column "
            f"{cfg.column!r} every {cfg.poll_s}s; the last read of each one stopped at nothing",
            data,
        )

    return probes.run_probe("intake", _read, request_id=request_id)


def _stamp(out: dict[str, Any], role: str) -> dict[str, Any]:
    """Add version, apparatus, role and time to an aggregated probe result."""
    out["version"] = __version__
    out["apparatus"] = APPARATUS_VERSION
    out["role"] = role
    out["checked_at"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    return out


def collect_health(
    factory: sessionmaker[Session],
    settings: Settings,
    *,
    role: str | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    """The deep probe (readiness). ``role`` defaults to :func:`process_role``;
    ``request_id`` is what a failed read's detail names (the route passes the middleware's).
    Every probe runs under :func:`probes.run_probe` — the observability probes here too,
    so no probe in the body can serve an exception."""
    role = process_role() if role is None else role
    rid = request_id
    results = [
        probe_db(factory, request_id=rid),
        probe_migrations(factory, request_id=rid),
        probe_append_only(factory, request_id=rid),
        probe_ledger(factory, request_id=rid),
        probes.run_probe(
            "sandbox", lambda: probe_sandbox(settings, role, request_id=rid), request_id=rid
        ),
        probes.run_probe("provision", lambda: probe_provision_role(settings, role), request_id=rid),
        probes.run_probe("toolchains", probes.probe_toolchains, request_id=rid),
        probes.run_probe("builders", probes.probe_builders, request_id=rid),
        probe_worker(factory, settings.worker_heartbeat_stale_s, request_id=rid),
        probe_intake(factory, settings, request_id=rid),
    ]
    return _stamp(probes.aggregate(results), role)


def collect_liveness(
    factory: sessionmaker[Session], *, role: str | None = None, request_id: str = ""
) -> dict[str, Any]:
    """Liveness: the process is up and its database answers. Exactly ONE probe (``db``);
    never the sandbox, the toolchains, the builders, the ledger or the worker — a
    liveness check that fails on a dependency restarts a healthy process."""
    role = process_role() if role is None else role
    return _stamp(probes.aggregate([probe_db(factory, request_id=request_id)]), role)


# --- routes -------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Deep health / readiness (503 when any probe is down; sandbox skipped for CRB_ROLE=api)",
)
def health(
    request: Request, response: Response, factory: SessionFactoryDep, settings: SettingsDep
) -> dict[str, Any]:
    """Readiness: 503 only on ``down`` — ``degraded`` still serves (with caveats)."""
    out = collect_health(factory, settings, request_id=request_id(request))
    if out["status"] == DOWN:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return out


@router.get(
    "/health/live",
    summary="Liveness: process up + database reachable (503 otherwise); never probes the sandbox",
)
def health_live(request: Request, response: Response, factory: SessionFactoryDep) -> dict[str, Any]:
    """Liveness: the process and its database, nothing else (see ``collect_liveness``)."""
    out = collect_liveness(factory, request_id=request_id(request))
    if out["status"] == DOWN:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return out


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    responses={404: _ERR, 503: _ERR},
    summary="Prometheus exposition (crb_false_q1_total must read 0)",
)
def prometheus_metrics(factory: SessionFactoryDep, settings: SettingsDep) -> Response:
    """The exposition; the ledger gauges are refreshed on every scrape so
    ``crb_false_q1_total`` is never stale."""
    if not settings.metrics_enabled:
        raise ApiError(404, "metrics_disabled", "CRB_METRICS_ENABLED is false")
    if not metrics.available():
        raise ApiError(503, "metrics_unavailable", "prometheus_client is not installed")
    refresh_ledger_gauges(factory)
    return Response(content=metrics.render(), media_type=CONTENT_TYPE_LATEST)


@router.get("/version", summary="Package, apparatus and routing-policy versions")
def version(request: Request) -> dict[str, Any]:
    """Package, apparatus and routing-policy versions plus uptime — what a claim cites."""
    started = float(getattr(request.app.state, "started_at", 0.0) or 0.0)
    return {
        "crb": __version__,
        "apparatus": APPARATUS_VERSION,
        "policy": POLICY_VERSION,
        "uptime_s": int(time.time() - started) if started else 0,
        # whether an organisation sign-in exists is a fact the login page and the posture
        # page both need before anyone is signed in; it names no provider and no secret
        "oidc_enabled": getattr(request.app.state, "oidc_client", None) is not None,
    }


__all__ = [
    "DEFAULT_ROLE",
    "MIGRATE_FIX",
    "ROLES",
    "ROLE_ALL",
    "ROLE_API",
    "ROLE_ENV",
    "ROLE_WORKER",
    "SKIPPED",
    "collect_health",
    "collect_liveness",
    "ledger_counts",
    "migrations_result",
    "probe_migrations",
    "probe_provision_role",
    "probe_worker",
    "process_role",
    "refresh_ledger_gauges",
    "router",
]
