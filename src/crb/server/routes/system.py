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
  down: complete, but unstamped until ``crb migrate`` runs. A store AT head is compared
  with the models too (pilot D7): ``ok`` only when they are equal, ``degraded`` naming each
  difference (``drift``) when the schema was changed outside the migrations.
* ``append_only`` — every expected ledger trigger is LIVE (on its own table with the
  installer's whole definition; on PostgreSQL enabled and calling ``crb_append_only`` —
  :func:`crb.store.db.expected_triggers`) AND an ``UPDATE`` and a ``DELETE`` are refused in
  the trigger's own words on every append-only table that holds a row, on SQLite a
  ``REPLACE`` too (:func:`crb.store.ledger.assert_append_only`; on empty tables none is
  tried and the detail says so; any other error is ``down``, never proof). A missing,
  moved, disabled or ``WHEN``-neutered trigger = ``down``, named in ``data.missing``.
* ``ledger``      — row count and ``false_q1`` computed in SQL with the same belt
  semantics as :func:`crb.core.ledger.false_q1_total`; any false-Q1 row = ``down``; and
  the sign-off and review chains walked from their stored columns — a break = ``down``.
  The same numbers refresh the ``crb_false_q1_total`` / ``crb_ledger_rows`` gauges.
* ``redaction``   — the newest :data:`REDACTION_PROBE_PACKS` stored evidence packs carry no
  credential shape the redactor knows (G-400): every string of each pack is re-run through
  :func:`crb.core.redact.redact`, and a pack leaks when the redactor would ADD a marker the
  string does not already carry — its own ``[REDACTED…]`` markers, whole or cut at the end
  by the head cap, are counted first, so neither a marker nor the word after one is ever
  read as a secret (P-640). A leaking pack is ``down`` and the detail names the pack hash,
  never the value; a pack body that cannot be read is ``degraded``, never down. The way
  back (DL-313): a pack is never deleted (the table is append-only), so an approver
  acknowledges it — after rotating the credential — at ``POST
  /system/redaction/{pack_hash}/acknowledge``; the act is a ``redaction.acknowledged`` event
  on the audit chain and the probe reads the pack as acknowledged, ``ok``, naming it. Known
  shapes only, in stored packs only — a secret of a shape the redactor does not know is not
  seen here. An ``ok`` reading is reused for :data:`REDACTION_PROBE_TTL_S` (one worker
  heartbeat).
* ``worker``      — liveness from the ``workers`` table each worker upserts every
  ``heartbeat_s`` even when idle (J-TEL-2): a worker seen within 3 × its own
  ``heartbeat_s`` is alive. ``degraded`` (never ``down``) when runs are queued and no
  worker is alive — nothing will start, and the sentence says so with the queue depth
  and the last check-in; when no worker has checked in yet; when one stopped checking
  in (named, with its age); when a running run's ``heartbeat`` is older than
  ``worker_heartbeat_stale_s``; or when a worker's row says it is still reaping a
  container whose ``docker kill`` the daemon never confirmed (``unconfirmed_containers``
  > 0 — src/crb/server/reaper.py; the container may still be running on that host); or
  when an alive worker's metrics listener is ``degraded`` (it could not bind its port —
  pilot D5; each worker's listener, read from its ``worker.metrics`` event, is in
  ``data.workers[].metrics``); ``ok`` otherwise with the workers listed. The worker is
  a dependency the API pod does not own: ``/health`` is the API's readiness probe, and a
  503 for a crashed worker would take every API pod out of the Service — exactly when
  the person needs to read "no worker has checked in" (the same rule as the sandbox
  probe for the ``api`` role). Before the table existed the probe read running runs'
  heartbeats only, so a crashed worker with three queued runs answered ``ok "idle, 3
  queued"``.
* ``builders``    — which builder credentials are present AND, for each login a run could use
  (every auth mode with a present credential or a recorded verification, not only the
  default), whether it works: ``verified`` / ``unverified`` / ``invalid`` from the recorded
  verifications with its age (pilot D1, src/crb/server/builder_login.py) — never ``ok`` from
  presence alone, never a model call; ``degraded`` (never ``down``) naming the login and
  where to fix it; presence and state only, never a fingerprint or a token source (F25).
* ``sandbox``     — the docker daemon answers (``docker`` executor) — **role-aware**:
  the sandbox is the WORKER's instrument. A process whose role is ``api`` (the
  ``serve`` container: no docker socket, by design — see ``deploy/Dockerfile``)
  reports the probe ``skipped``, never ``degraded``/``down``: a missing socket there
  is the intended posture, not a fault, and must not fail the API's health. The
  role is read from ``CRB_ROLE`` (:func:`process_role`; ``api`` | ``worker`` |
  ``all``, default ``all`` = one process does both, so everything is probed).
* ``build``       — the served commits agree (:mod:`crb.observability.build_stamp`): the
  commit this process was started from, the checkout's commit now and the commit the
  served UI bundle was built from. Any disagreement — or a served bundle with no stamp —
  is ``degraded`` (never ``down``: stale code still serves) with the fix in the sentence,
  and the body's top-level ``served`` carries the three commits and ``stale``
  (docs/PREVENTION.md P-002: the stack once served code behind ``origin/main`` and a UI
  built from an older tree, and nothing said so).

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
              table) and the served-commit ``build`` probe (``served`` + ``stale``) with the
              observability probes
              (sandbox — skipped for the ``api`` role — toolchains, builders with each
              present login's verification state) and answers
              503 when any is ``down``, and serves the deployment's ``posture`` beside them
              (where tests and the builder run, and whether production runs unsealed under
              ``CRB_ALLOW_UNSEALED_PROD``, ADR-0023); a read that raises is ``down`` with
              the fixed ``failure_detail`` naming the request id, the exception logged, never
              served;
              liveness checks the database only; ``/metrics``
              refreshes the ledger gauges and each repository's one-hot
              ``crb_controls_verdict`` (from the latest controls report, at scrape time, so a
              restart cannot blank it — G-920) then renders the shared registry;
              ``disqualified_counts`` is the ``disqualified`` block ``/ledger/verify`` serves
              (per builder over the last seven days against DL-312's threshold, G-400);
              ``POST /system/redaction/{pack_hash}/acknowledge`` (approver) records the way
              back from a ``redaction`` stop on the audit chain (DL-313).
              ``/health`` and ``/version`` say whether automatic sign-in is on (never which
              account, and ``on`` only to a caller that could use it), and
              ``probe_dev_autologin`` is the doctor line that warns while it is.
How:          ``collect_health`` = the probe list, each under ``probes.run_probe`` with the
              request id → ``probes.aggregate`` → stamp;
              ``migrations_result`` turns a ``HeadStatus`` into the probe (``crb doctor``
              renders the same function from a bare URL);
              ``ledger_counts`` is the SQL twin of ``false_q1_total`` over the stored
              belts; ``process_role`` reads ``CRB_ROLE`` so the API container never fails
              on the docker socket it is not meant to have.
Layer:        server — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0011-repo-lint-belt.md (belt 5 in the false-Q1 predicate),
              docs/adr/0023-production-refuses-the-unsealed-posture.md (the ``posture`` key),
              docs/adr/0027-dev-autologin-on-loopback.md (the ``dev_autologin`` field)
Works with:   src/crb/observability/probes.py (the probe vocabulary, ``run_probe`` /
              ``failure_detail`` and ``aggregate``; its sibling build_stamp.py is the
              ``build`` probe and the ``served`` block),
              src/crb/server/auth.py (``dev_autologin_refusal`` — who is told automatic
              sign-in is on),
              src/crb/store/migrate.py (``head_status_on`` — the one head check; the ledger
              probe calls ``assert_append_only`` in src/crb/store/ledger.py; the
              ``append_only`` probe counts ``expected_triggers`` from src/crb/store/db.py),
              src/crb/cli/commands/service.py (``crb doctor`` renders ``migrations_result``
              and ``probe_worker``),
              src/crb/observability/metrics.py (the gauges and the registry — the API's
              series only; the worker serves its own, docs/DEPLOYMENT.md#9-observability),
              src/crb/server/worker.py (upserts
              the ``workers`` rows the worker probe reads; the false-Q1 predicate is kept in
              step with src/crb/server/routes/signoffs.py), deploy/entrypoint.sh + deploy/Dockerfile
              (``CRB_ROLE`` per container and the ``HEALTHCHECK`` on ``/health/live``),
              docs/API.md#health--metrics-no-auth-bind-to-an-internal-interface (the
              ``migrations`` contract the other documents copy)
Tested by:    tests/test_server_system.py, tests/test_deploy_health_probes.py,
              tests/test_settings_posture.py, tests/test_server_dev_autologin.py,
              tests/test_health_probe_docs.py, tests/test_ledger_disqualified.py
Touch when:   never for a new repository; adding a probe means deciding which role owns it
              (``skipped`` elsewhere), whether it may fail readiness, and putting its read
              under ``probes.run_probe`` (never an exception in a ``detail``); a new belt means
              extending the predicate here AND in ``FALSE_Q1_PREDICATE`` (signoffs.py) AND
              ``false_q1_total`` in src/crb/core/ledger.py together.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import BELT_SET_V3_LEGACY, BELT_SET_V5, LedgerIntegrityError
from crb.core.redact import redact
from crb.core.routing import POLICY_VERSION
from crb.core.secrets_file import SecretsError
from crb.core.signoff import SIGNOFF_POLICY_VERSION
from crb.core.version import APPARATUS_VERSION, __version__
from crb.intake.client import STOP_ADVICE, TRACKER_TOKEN_SECRET
from crb.observability import build_stamp, metrics, probes
from crb.observability.metrics import EXPOSITION_DEGRADED
from crb.observability.probes import DEGRADED, DOWN, OK, ProbeResult
from crb.provision.probe import probe_provision
from crb.server.auth import ApproverDep, dev_autologin_refusal
from crb.server.builder_login import (
    FIX_WHERE,
    STATE_INVALID,
    STATE_UNVERIFIED,
    STATE_VERIFIED,
    login_readings,
)
from crb.server.deps import (
    ApiError,
    DbDep,
    ErrorEnvelope,
    SessionFactoryDep,
    SettingsDep,
    request_id,
)
from crb.server.flow_record import stamp_first_healthy
from crb.server.intake import IntakeStore, ListenerState, needs_credential
from crb.server.routes.oracle import latest_controls_verdict, verdict_dict
from crb.server.routes.reviews import verify_reviews
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.routes.signoffs import verify_signoffs
from crb.server.schemas import RedactionAckIn, RedactionAckOut
from crb.server.secrets import SecretsFile, secrets_dir_for
from crb.server.settings import Settings
from crb.server.worker_metrics import exposition_by_worker
from crb.store.db import expected_triggers, live_triggers
from crb.store.ledger import assert_append_only
from crb.store.migrate import HeadStatus, head_status_on
from crb.store.models import (
    LEASE_ROW_PREFIX,
    Event,
    EvidencePackRow,
    Grade,
    Repo,
    Run,
    User,
    WorkerRow,
)

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
    surfaces cannot disagree. ``ok`` at head with a schema that matches the models;
    ``degraded`` at head with a schema that differs (named — pilot D7) and for a
    ``create_all`` schema that equals the head but carries no ``alembic_version``
    (complete; ``crb migrate`` stamps it);
    ``down`` otherwise — behind, ahead, empty or an older unversioned schema — naming the
    revisions where applicable and the fix."""
    data = st.to_dict()
    if st.at_head and st.matches_models:
        return ProbeResult("migrations", OK, f"database at {st.head} = code head", data)
    if st.at_head:
        # pilot D7 (P-437): at head by its stamp, but compared with the models it differs —
        # a schema changed outside the migrations; the revision number alone is not "ok"
        return ProbeResult(
            "migrations",
            DEGRADED,
            f"database at {st.head} = code head, but its schema differs from the models: "
            f"{'; '.join(st.drift) or 'unnamed difference'} — it was changed outside the "
            "migrations; compare it with a fresh `crb migrate` store and restore it",
            data,
        )
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


#: What the ``append_only`` probe says when it passes and a write was tried.
APPEND_ONLY_OK_DETAIL = (
    "triggers live on every append-only table; UPDATE and DELETE refused on each that holds a row"
)
#: What it says when it passes on a store whose append-only tables are all empty: no write
#: was tried, so it claims none was refused (P-216) — the live-trigger check is the proof.
APPEND_ONLY_UNTRIED_DETAIL = "triggers live on every append-only table; no row to test a write on"


def probe_append_only(factory: sessionmaker[Session], *, request_id: str = "") -> ProbeResult:
    """``append_only``: every expected trigger LIVE (present on its own table with the
    installer's whole definition, enabled, and calling the append-only function) AND
    :func:`crb.store.ledger.assert_append_only` — an UPDATE and a DELETE refused in the
    trigger's own words on every table that holds a row, on SQLite a ``REPLACE`` too
    (counting names alone passed a trigger that exists but does not fire). On a store whose
    append-only tables are all empty no write is tried and the ``ok`` detail says so. An
    accepted write is ``down`` in the ledger's own words (:class:`LedgerIntegrityError`
    names no secret); any other error — the probe no longer reads one as proof (P-125) — is
    ``down`` with the fixed ``failure_detail``. A ``down`` names the missing triggers in
    ``data.missing``."""

    def _read() -> ProbeResult:
        with factory() as s:
            names = [n for _, n in expected_triggers(s.get_bind().dialect.name)]
            live = live_triggers(s.connection())
        expected = len(names)
        missing = sorted(n for n in names if n not in live)
        data: dict[str, Any] = {"triggers": expected - len(missing), "expected": expected}
        if missing:
            data["missing"] = missing
        if missing:
            return ProbeResult(
                "append_only",
                DOWN,
                f"{expected - len(missing)}/{expected} append-only triggers present",
                data,
            )
        try:
            tried = assert_append_only(factory)
        except LedgerIntegrityError as exc:
            return ProbeResult("append_only", DOWN, str(exc), data)
        # never claim a write that was not tried: on empty tables the live-trigger check is
        # the whole proof
        detail = APPEND_ONLY_OK_DETAIL if tried else APPEND_ONLY_UNTRIED_DETAIL
        return ProbeResult("append_only", OK, detail, data)

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


def refresh_controls_gauges(factory: sessionmaker[Session]) -> dict[str, str]:
    """Set ``crb_controls_verdict{repo,state}`` one-hot for every repository from its latest
    ``controls.report`` at the running apparatus (``latest_controls_verdict`` — the same read
    the router and the Oracle screen make) and return ``{repo: state}``. Called at SCRAPE
    time by ``/metrics``, not by the worker on ``controls.report``: a gauge the worker set
    would read absent after every API restart until the next controls run, and an alert on
    ``state!="passed"`` would fall silent exactly when the deployment came back (G-920)."""
    states: dict[str, str] = {}
    with factory() as s:
        names = [str(n) for n in s.execute(select(Repo.name).order_by(Repo.name)).scalars()]
        for name in names:
            states[name] = str(verdict_dict(latest_controls_verdict(s, name))["state"])
    for name, state in states.items():
        metrics.set_controls_verdict(name, state)
    return states


#: The ``disqualified`` block of ``GET /ledger/verify`` (DL-312, G-400): rows graded
#: ``disqualified`` in the last :data:`DISQUALIFIED_WINDOW_DAYS`, counted per builder, and a
#: builder at or over :data:`DISQUALIFIED_THRESHOLD` of them is a stop condition
#: (docs/OPERATOR.md#8-stop-conditions). The threshold is a hypothesis until a deployment
#: has measured its own base rate — DL-312 says how to change it.
DISQUALIFIED_WINDOW_DAYS = 7
DISQUALIFIED_THRESHOLD = 2


def disqualified_counts(session: Session, *, now: _dt.datetime | None = None) -> dict[str, Any]:
    """``{window_days, threshold, by_builder: [{builder, n}], over: [builder]}`` over the
    grade rows created in the last :data:`DISQUALIFIED_WINDOW_DAYS` (``created`` is an
    ISO-8601 UTC string, so the cut is a string compare against one), disqualified rows
    only, per builder, descending by count then by name; ``over`` names the builders at or
    past :data:`DISQUALIFIED_THRESHOLD`."""
    at = now or _dt.datetime.now(_dt.UTC)
    since = (at - _dt.timedelta(days=DISQUALIFIED_WINDOW_DAYS)).isoformat(timespec="seconds")
    rows = session.execute(
        select(Grade.builder, func.count(Grade.seq))
        .where(Grade.disqualified.is_(True), Grade.created >= since)
        .group_by(Grade.builder)
    ).all()
    counts = sorted(((str(b or ""), int(n)) for b, n in rows), key=lambda t: (-t[1], t[0]))
    return {
        "window_days": DISQUALIFIED_WINDOW_DAYS,
        "threshold": DISQUALIFIED_THRESHOLD,
        "by_builder": [{"builder": b, "n": n} for b, n in counts],
        "over": [b for b, n in counts if n >= DISQUALIFIED_THRESHOLD],
    }


def probe_ledger(factory: sessionmaker[Session], *, request_id: str = "") -> ProbeResult:
    """``ledger``: ``down`` on any false-Q1 row — the honesty floor is a readiness condition —
    and ``down`` when the sign-off or the review chain no longer verifies from its stored
    columns (EI-6, 2026-09-27: a licence altered under the triggers was served as active
    while every probe read ok). Both tables are small; the grades chain itself is walked by
    ``/ledger/verify``, not here."""

    def _read() -> ProbeResult:
        rows, fq1 = refresh_ledger_gauges(factory)
        with factory() as s:
            signoffs = verify_signoffs(s)
            reviews = verify_reviews(s)
        data = {
            "rows": rows,
            "false_q1": fq1,
            "signoffs": signoffs.rows,
            "signoffs_chain_ok": signoffs.chain_ok,
            "reviews": reviews.rows,
            "reviews_chain_ok": reviews.chain_ok,
        }
        if fq1:
            return ProbeResult("ledger", DOWN, f"false_q1={fq1} — honesty floor breached", data)
        broken = [
            f"{name} chain broken at {chain.detail}"
            for name, chain in (("sign-off", signoffs), ("review", reviews))
            if not chain.chain_ok
        ]
        if broken:
            return ProbeResult(
                "ledger", DOWN, "; ".join(broken) + " — the record was altered", data
            )
        return ProbeResult(
            "ledger",
            OK,
            f"{rows} rows, false_q1=0; sign-off and review chains intact",
            data,
        )

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


def _worker_view(
    row: WorkerRow, now: _dt.datetime, exposition: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """One worker for ``data.workers`` (and the UI): its check-in age against the
    staleness it promised, whether it is alive, what it holds, a clean stop, and what its
    metrics listener did at start (``metrics``: ``None`` when it recorded nothing)."""
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
        "metrics": dict(exposition) if exposition else None,
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
            rows = list(
                s.execute(
                    select(WorkerRow)
                    # a lease row (an intake pass holding its repository) is not a worker
                    .where(~WorkerRow.worker_id.startswith(LEASE_ROW_PREFIX))
                    .order_by(WorkerRow.worker_id)
                ).scalars()
            )
        listed = [
            r
            for r in rows
            if not r.stopped or (_age_s(r.heartbeat, now) or 0.0) <= WORKER_FORGET_AFTER_S
        ]
        # what each listed worker's metrics listener did at start (pilot D5)
        listeners = exposition_by_worker(factory, [r.worker_id for r in listed])
        workers = [_worker_view(r, now, listeners.get(r.worker_id)) for r in listed]
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
        deaf = [w for w in alive if (w["metrics"] or {}).get("state") == EXPOSITION_DEGRADED]
        if deaf:
            # pilot D5 (P-436): the worker runs and measures, but its series go nowhere
            w = deaf[0]
            return ProbeResult(
                "worker",
                DEGRADED,
                f"worker {w['worker_id']} is running but its metrics listener is not: "
                f"{w['metrics'].get('reason') or 'no reason recorded'}",
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


def dev_autologin_state(settings: Settings, request: Request | None = None) -> str:
    """``on`` / ``off``: whether automatic sign-in is switched on (ADR-0027). ``/health``
    says it at the top level — beside the probes, not as one, so a development stack's
    readiness is not lowered by a setting the operator chose — and names no account.

    Given the ``request``, it says ``on`` only to a caller the route would sign in
    (:func:`crb.server.auth.dev_autologin_refusal` finds nothing); any other caller — another
    machine, a proxied request, another host name — reads ``off``, exactly what a stack
    without it serves, so the answer tells a caller that cannot use it nothing. ``crb doctor``
    reads the settings directly (:func:`probe_dev_autologin`), so the operator is never told
    ``off`` while it is on."""
    if not settings.auth.dev_autologin:
        return "off"
    if request is not None and dev_autologin_refusal(request) is not None:
        return "off"
    return "on"


def probe_dev_autologin(settings: Settings | None) -> ProbeResult:
    """``crb doctor``'s ``dev_autologin`` line: ``ok`` "off", or ``degraded`` (``warn``) with
    the account named while it is on; ``skipped`` when the settings could not be read."""
    if settings is None:
        return ProbeResult(
            "dev_autologin", SKIPPED, "not checked: the settings could not be read", {}
        )
    name = settings.auth.dev_autologin
    if not name:
        return ProbeResult("dev_autologin", OK, "off", {"enabled": False})
    return ProbeResult(
        "dev_autologin",
        DEGRADED,
        f"on — a browser on this machine is signed in as {name!r} without a password "
        "(CRB_AUTH__DEV_AUTOLOGIN); development stacks only, never use in production",
        {"enabled": True, "username": name},
    )


#: How many of the newest stored evidence packs the ``redaction`` probe re-reads.
REDACTION_PROBE_PACKS = 50
#: How long a reading is reused: one worker heartbeat (``heartbeat_s`` defaults to 10 s), so
#: a readiness poll every few seconds does not re-walk fifty packs each time, and a pack
#: stored since is seen within a heartbeat. A reading that is not ``ok`` is not cached at
#: all, so a fixed store is seen at once.
REDACTION_PROBE_TTL_S = 10.0
#: The redactor's own whole markers — ``[REDACTED]``, ``[REDACTED-KEY]``,
#: ``[REDACTED-PRIVATE-KEY]`` — and a marker the head cap cut at the end of a string
#: (``[REDAC …``: ``redact_and_cap_head`` cuts anywhere and appends `` …``). Both are COUNTED,
#: never cut out, before and after the redactor is re-run (:func:`carries_secret_shape`):
#: cutting a marker out re-created the shape it stood in — ``token=[REDACTED] mismatch``
#: became ``token= mismatch``, which the ``key=value`` rule re-matches on the next word — and
#: the six-character cut ``[REDAC`` is itself a value that rule accepts (P-640, the Wave 6
#: plan critique and its verifiers, 2026-09-29).
_MARKER_WHOLE = re.compile(r"\[REDACTED(?:-[A-Z-]+)?\]")
_MARKER_CUT = re.compile(
    r"\[(?:R(?:E(?:D(?:A(?:C(?:T(?:E(?:D(?:-[A-Z-]*)?)?)?)?)?)?)?)?)?(?=\s*…\s*$)"
)
#: The audit-chain action an approver's acknowledgement writes (DL-313): the way back from a
#: ``redaction`` stop for a pack that is never deleted. ``payload = {pack_hash, reason}``.
REDACTION_ACK_ACTION = "redaction.acknowledged"
#: Per store (the factory's bind URL), like the provision cache is per configuration, so two
#: stores in one process — the test suite's — never read each other's packs.
_redaction_cache: dict[str, tuple[float, ProbeResult]] = {}
_redaction_lock = threading.Lock()


def _store_key(factory: sessionmaker[Session]) -> str:
    bind = dict(getattr(factory, "kw", {}) or {}).get("bind")
    url = getattr(bind, "url", None)
    return str(url) if url is not None else f"factory:{id(factory)}"


def _marker_count(text: str) -> int:
    """How many of the redactor's own markers ``text`` carries — whole ones anywhere, plus a
    cut one at the end (the head cap's ``[REDAC …``)."""
    return len(_MARKER_WHOLE.findall(text)) + (1 if _MARKER_CUT.search(text) else 0)


def carries_secret_shape(text: str) -> bool:
    """``True`` when re-running the redactor would ADD a marker ``text`` does not already
    carry — a credential shape whose captured value is not one of the redactor's own
    markers, whole or cut. A marker the redactor merely rewrites in place (``token:
    [REDACTED]`` → ``token=[REDACTED]``) adds none and is not a secret."""
    return _marker_count(redact(text)) > _marker_count(text)


def acknowledged_packs(session: Session) -> dict[str, dict[str, str]]:
    """``{pack_hash: {actor, reason, at}}`` for every :data:`REDACTION_ACK_ACTION` event on
    the chain (the first record of each pack wins — the act is idempotent)."""
    rows = session.execute(
        select(Event.payload_json, Event.actor, Event.timestamp)
        .where(Event.action == REDACTION_ACK_ACTION, Event.stage == "system")
        .order_by(Event.id)
    ).all()
    out: dict[str, dict[str, str]] = {}
    for payload, actor, at in rows:
        pack_hash = str(dict(payload or {}).get("pack_hash") or "")
        if pack_hash and pack_hash not in out:
            out[pack_hash] = {
                "actor": str(actor or ""),
                "reason": str(dict(payload or {}).get("reason") or ""),
                "at": str(at or ""),
            }
    return out


def _strings_of(value: Any) -> Iterator[str]:
    """Every string in a JSON-shaped value, keys included (a key can carry a value)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _strings_of(k)
            yield from _strings_of(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings_of(v)


def redaction_result(factory: sessionmaker[Session]) -> ProbeResult:
    """One uncached reading of the ``redaction`` probe (see the module docstring)."""
    with factory() as s:
        packs = list(
            s.execute(
                select(EvidencePackRow.pack_hash, EvidencePackRow.body_json)
                .order_by(EvidencePackRow.created.desc(), EvidencePackRow.pack_hash)
                .limit(REDACTION_PROBE_PACKS)
            ).all()
        )
        acked = acknowledged_packs(s)
    leaking: list[str] = []
    acknowledged: list[str] = []
    unreadable: list[str] = []
    for pack_hash, body in packs:
        try:
            found = any(carries_secret_shape(text) for text in _strings_of(body))
        except Exception:  # one pack's read must not decide the others'
            unreadable.append(str(pack_hash))
            continue
        if found and str(pack_hash) in acked:
            acknowledged.append(str(pack_hash))
        elif found:
            leaking.append(str(pack_hash))
    data = {
        "packs": len(packs),
        "window": REDACTION_PROBE_PACKS,
        "leaking": leaking,
        "acknowledged": acknowledged,
        "unreadable": unreadable,
    }
    if leaking:
        n = len(leaking)
        return ProbeResult(
            "redaction",
            DOWN,
            f"a credential shape the redactor knows is in {_plural(n, 'stored evidence pack')}"
            f" — pack {leaking[0]}"
            + (f" and {n - 1} more" if n > 1 else "")
            + " — stop delivery, rotate the credential, then an approver acknowledges the "
            "pack (docs/OPERATOR.md#8-stop-conditions); the value is not served",
            data,
        )
    if unreadable:
        return ProbeResult(
            "redaction",
            DEGRADED,
            f"{_plural(len(unreadable), 'stored evidence pack')} could not be read — "
            f"pack {unreadable[0]} — the others carry no known credential shape",
            data,
        )
    if not packs:
        return ProbeResult(
            "redaction", OK, "no stored evidence pack yet; nothing to re-check", data
        )
    noted = (
        f"; {_plural(len(acknowledged), 'pack')} acknowledged by an approver after rotation"
        f" — {acknowledged[0]}"
        + (f" and {len(acknowledged) - 1} more" if len(acknowledged) > 1 else "")
        if acknowledged
        else ""
    )
    return ProbeResult(
        "redaction",
        OK,
        f"the newest {_plural(len(packs), 'stored evidence pack')} carry no credential shape "
        f"the redactor knows (known shapes only){noted}",
        data,
    )


def probe_redaction(factory: sessionmaker[Session], *, request_id: str = "") -> ProbeResult:
    """``redaction`` (G-400): :func:`redaction_result`, an ``ok`` reading reused for
    :data:`REDACTION_PROBE_TTL_S`; a store that cannot be read is ``down`` with the fixed
    ``failure_detail`` (``run_probe``)."""
    key = _store_key(factory)
    now = _monotonic()
    with _redaction_lock:
        hit = _redaction_cache.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]

    def _read() -> ProbeResult:
        result = redaction_result(factory)
        with _redaction_lock:
            if result.status == OK:
                _redaction_cache[key] = (now + REDACTION_PROBE_TTL_S, result)
            else:
                _redaction_cache.pop(key, None)
        return result

    return probes.run_probe("redaction", _read, request_id=request_id)


def probe_builder_logins(
    factory: sessionmaker[Session], settings: Settings, *, request_id: str = ""
) -> ProbeResult:
    """``builders``: which builder credentials are PRESENT (``probes.probe_builders``) and, for
    each login a run could use — every builder with a verify, in its default auth mode and in
    every other mode with a present credential or a recorded verification (Q1's review) —
    whether it WORKS: ``verified``, ``unverified`` or ``invalid`` from the recorded
    verifications with its age (pilot D1, P-435). Never ``ok`` from presence alone, and never
    a model call: the cache is refreshed by a submit that finds it stale and by Verify on the
    Settings screen. ``degraded`` (never ``down`` — a dead login is the operator's to fix, and
    the API must stay reachable for them to fix it) when any present login is invalid, or the
    default one is not verified, naming it, its age and where to fix it. ``/health`` answers
    without a session, so it carries a viewer's view of each login: presence and state, never
    the fingerprint, the token source or the verification's words (F25)."""

    def _read() -> ProbeResult:
        base = probes.probe_builders()
        with factory() as s:
            readings = login_readings(
                s, ttl_s=settings.builder.login_ttl_s, secrets_dir=secrets_dir_for(settings)
            )
        logins = [{**r.to_dict(full=False), "sentence": r.sentence(full=False)} for r in readings]
        data = {**base.data, "logins": logins}
        live = [x for x in logins if x["present"]]
        bad = [x for x in live if x["state"] == STATE_INVALID]
        if bad:
            return ProbeResult(
                "builders",
                DEGRADED,
                f"login invalid — {bad[0]['sentence']}; no run on it will be queued until it is "
                f"fixed under {FIX_WHERE}",
                data,
            )
        unknown = [x for x in live if x["default"] and x["state"] == STATE_UNVERIFIED]
        if unknown:
            return ProbeResult(
                "builders",
                DEGRADED,
                f"login not verified — {unknown[0]['sentence']}; press Verify under {FIX_WHERE} "
                "(a run's submit also verifies it once before queuing)",
                data,
            )
        verified = "; ".join(x["sentence"] for x in live if x["state"] == STATE_VERIFIED)
        detail = f"{base.detail}; {verified}" if verified else base.detail
        return ProbeResult("builders", base.status, detail, data)

    return probes.run_probe("builders", _read, request_id=request_id)


#: ``collect_health`` without the app's mounted UI directory (a caller outside a request):
#: the probe then resolves the candidates itself.
UI_DIST_UNKNOWN: Any = object()


def probe_served(
    settings: Settings, *, request_id: str = "", ui_dist: Path | None = UI_DIST_UNKNOWN
) -> ProbeResult:
    """``build``: the commit this process runs, the checkout's and the served UI bundle's
    agree (``degraded`` when not — see :func:`crb.observability.build_stamp.probe_build`).
    ``ui_dist`` is the directory the app MOUNTED at start-up (``app.state.ui_dist``;
    ``None`` = no UI served): the bundle compared is the one served, never a fresh look-up
    that a directory appearing or vanishing since start-up would change."""

    def _read() -> ProbeResult:
        if ui_dist is not UI_DIST_UNKNOWN:
            return build_stamp.probe_build(ui_dist)
        from crb.server.app import resolve_ui_dist  # noqa: PLC0415 — the app imports this module

        return build_stamp.probe_build(resolve_ui_dist(settings))

    return probes.run_probe("build", _read, request_id=request_id)


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
    request: Request | None = None,
    ui_dist: Path | None = UI_DIST_UNKNOWN,
) -> dict[str, Any]:
    """The deep probe (readiness). ``role`` defaults to :func:`process_role``;
    ``request_id`` is what a failed read's detail names (the route passes the middleware's);
    ``request`` decides who is told that automatic sign-in is on (:func:`dev_autologin_state`).
    Every probe runs under :func:`probes.run_probe` — the observability probes here too,
    so no probe in the body can serve an exception."""
    role = process_role() if role is None else role
    rid = request_id
    results = [
        probe_db(factory, request_id=rid),
        probe_migrations(factory, request_id=rid),
        probe_append_only(factory, request_id=rid),
        probe_ledger(factory, request_id=rid),
        probe_redaction(factory, request_id=rid),
        probes.run_probe(
            "sandbox", lambda: probe_sandbox(settings, role, request_id=rid), request_id=rid
        ),
        probes.run_probe("provision", lambda: probe_provision_role(settings, role), request_id=rid),
        probes.run_probe("toolchains", probes.probe_toolchains, request_id=rid),
        probe_builder_logins(factory, settings, request_id=rid),
        probe_worker(factory, settings.worker_heartbeat_stale_s, request_id=rid),
        probe_intake(factory, settings, request_id=rid),
        probe_served(settings, request_id=rid, ui_dist=ui_dist),
    ]
    out = _stamp(probes.aggregate(results), role)
    out["dev_autologin"] = dev_autologin_state(settings, request)
    # ADR-0023: where tests and the builder run, and whether production runs unsealed under
    # CRB_ALLOW_UNSEALED_PROD — a fact every viewer of the Posture page is owed, not a probe
    # (it cannot fail; it is what this deployment was told)
    out["posture"] = settings.posture()
    # the served commits and `stale` at the top level, so a reader need not find the probe
    # (``{}`` when the read itself failed — the probe then says so with the request id)
    out["served"] = next((p["data"] for p in out["probes"] if p["name"] == "build"), {})
    return out


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
    state = request.app.state
    mounted = state.ui_dist if getattr(state, "ui_mounted", False) else UI_DIST_UNKNOWN
    out = collect_health(
        factory, settings, request_id=request_id(request), ui_dist=mounted, request=request
    )
    # ADR-0028: the first green read is the go-live stream's end mark, stamped once
    stamp_first_healthy(factory, str(out["status"]))
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
    """The exposition; the ledger gauges and each repository's ``crb_controls_verdict`` are
    refreshed on every scrape so neither is ever stale, and a restart blanks nothing."""
    if not settings.metrics_enabled:
        raise ApiError(404, "metrics_disabled", "CRB_METRICS_ENABLED is false")
    if not metrics.available():
        raise ApiError(503, "metrics_unavailable", "prometheus_client is not installed")
    refresh_ledger_gauges(factory)
    refresh_controls_gauges(factory)
    return Response(content=metrics.render_api(), media_type=CONTENT_TYPE_LATEST)


#: The package's licence — pyproject.toml's ``license`` (tests/test_server_app.py pins the
#: two together, so the Deployment page never states a licence the package does not carry).
LICENCE = "Apache-2.0"


def _ack_out(pack_hash: str, rec: Mapping[str, str]) -> RedactionAckOut:
    return RedactionAckOut(
        pack_hash=pack_hash,
        actor=str(rec.get("actor", "")),
        reason=str(rec.get("reason", "")),
        acknowledged_at=str(rec.get("at", "")),
    )


@router.post(
    "/system/redaction/{pack_hash}/acknowledge",
    response_model=RedactionAckOut,
    summary="Acknowledge a stored evidence pack the redaction probe named (approver; DL-313)",
    responses={
        404: {"model": ErrorEnvelope, "description": "no stored pack with that hash"},
        409: {"model": ErrorEnvelope, "description": "the pack carries no known credential shape"},
    },
)
def acknowledge_redaction(
    pack_hash: str, body: RedactionAckIn, approver: ApproverDep, db: DbDep
) -> RedactionAckOut:
    """The way back from a ``redaction`` stop (DL-313). The evidence table is append-only and
    a pack is never deleted, so after the credential is rotated an approver records that the
    named pack has been dealt with: one ``redaction.acknowledged`` system event on the audit
    chain (``payload = {pack_hash, reason}``, the actor stamped, the value never copied), and
    the probe reads the pack as acknowledged. Idempotent — a second call returns the first
    record. A pack the store does not hold is 404; a pack that carries no known shape is 409
    (nothing to acknowledge — the probe never named it)."""
    row = db.get(EvidencePackRow, pack_hash)
    if row is None:
        raise ApiError(404, "not_found", f"no stored evidence pack {pack_hash}")
    already = acknowledged_packs(db).get(pack_hash)
    if already is not None:
        return _ack_out(pack_hash, already)
    try:
        found = any(carries_secret_shape(text) for text in _strings_of(row.body_json))
    except Exception:
        found = False
    if not found:
        raise ApiError(
            409,
            "nothing_to_acknowledge",
            f"stored evidence pack {pack_hash} carries no credential shape the redactor knows",
        )
    ev = append_system_event(
        db,
        trace_id=system_trace_id("redaction", pack_hash),
        action=REDACTION_ACK_ACTION,
        repo=str(row.repo or ""),
        actor=approver.id,
        payload={"pack_hash": pack_hash, "reason": body.reason},
    )
    db.commit()
    with _redaction_lock:  # the next readiness read sees the acknowledgement at once
        _redaction_cache.clear()
    return _ack_out(pack_hash, {"actor": ev.actor, "reason": body.reason, "at": str(ev.timestamp)})


@router.get("/version", summary="Package, apparatus and routing-policy versions")
def version(request: Request) -> dict[str, Any]:
    """Package, apparatus and routing-policy versions plus uptime — what a claim cites.
    ``belt_set``, ``signoff_policy`` and ``licence`` are the values in force, so the
    Deployment page reads them rather than stating them (G-212)."""
    started = float(getattr(request.app.state, "started_at", 0.0) or 0.0)
    return {
        "crb": __version__,
        "apparatus": APPARATUS_VERSION,
        "policy": POLICY_VERSION,
        "belt_set": BELT_SET_V5,
        "signoff_policy": SIGNOFF_POLICY_VERSION,
        "licence": LICENCE,
        "uptime_s": int(time.time() - started) if started else 0,
        # whether an organisation sign-in exists is a fact the login page and the posture
        # page both need before anyone is signed in; it names no provider and no secret
        "oidc_enabled": getattr(request.app.state, "oidc_client", None) is not None,
        # the banner every page shows while automatic sign-in is on must render on the
        # sign-in page too, before anyone has a role; it names no account, and only a caller
        # the route would sign in is told it is on (ADR-0027)
        "dev_autologin": dev_autologin_state(request.app.state.settings, request) == "on",
    }


__all__ = [
    "DEFAULT_ROLE",
    "DISQUALIFIED_THRESHOLD",
    "DISQUALIFIED_WINDOW_DAYS",
    "LICENCE",
    "MIGRATE_FIX",
    "REDACTION_ACK_ACTION",
    "REDACTION_PROBE_PACKS",
    "ROLES",
    "ROLE_ALL",
    "ROLE_API",
    "ROLE_ENV",
    "ROLE_WORKER",
    "SKIPPED",
    "acknowledged_packs",
    "carries_secret_shape",
    "collect_health",
    "collect_liveness",
    "dev_autologin_state",
    "disqualified_counts",
    "ledger_counts",
    "migrations_result",
    "probe_dev_autologin",
    "probe_migrations",
    "probe_provision_role",
    "probe_redaction",
    "probe_worker",
    "process_role",
    "refresh_controls_gauges",
    "refresh_ledger_gauges",
    "router",
]
