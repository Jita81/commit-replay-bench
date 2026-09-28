"""The unsealed production override, on the audit trail: who set it, and why (G-663).

``CRB_ALLOW_UNSEALED_PROD=1`` lets production run the host builder or the local test executor
(ADR-0023). An environment variable carries no identity, so the override is refused in
production without a named acknowledgement beside it — ``CRB_ALLOW_UNSEALED_PROD_BY`` (the
username of an admin account) and ``CRB_ALLOW_UNSEALED_PROD_REASON`` — and every process that
starts under it (``crb serve`` and each ``crb worker``) checks the name against the store and
writes one ``posture.unsealed_override`` event naming that person and the reason, before it
serves a request or takes a run. A name that is no account, not an admin or deactivated
refuses the start and writes nothing.

The event is a statement by the deployment's operator that a named admin owns the decision;
the product cannot prove the admin typed the variable, only that an admin who exists was
named and that the naming is on the tamper-evident trail (ADR-0029).

Navigation
----------
What it is:   The start-up check and audit event for the unsealed production override.
What it does: Resolves ``CRB_ALLOW_UNSEALED_PROD_BY`` to exactly one active admin account
              (a local username, an identity-provider subject or an email) and refuses
              anything else with :class:`OverrideRefused`; writes one ``system`` event
              ``posture.unsealed_override`` whose actor is that account and whose payload
              names the username, the reason, the process and the posture it admits.
How:          ``record_unsealed_override`` = take the events write lock
              (``lock_event_writes``: the trace is shared by every process start) → ``find_acknowledging_admin`` = read
              the ``users`` table, match, check role and active → ``append_system_event`` on
              the fixed trace ``posture:unsealed_override`` → commit (the chain's flush hook
              hashes it).
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0023-production-refuses-the-unsealed-posture.md,
              docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/server/settings.py (``unsealed_override_ack_refusal`` — the static half:
              no name, no start), src/crb/server/app.py (the API's start-up calls it),
              src/crb/server/worker_main.py (``announce_start`` — the worker's),
              src/crb/server/routes/runs.py (``append_system_event`` writes the event),
              docs/API.md (the event's row in the vocabulary),
              docs/DEPLOYMENT.md#21-environment-reference (the two variables, for operators)
Tested by:    tests/test_settings_posture.py, tests/test_worker_start.py,
              tests/test_unsealed_override_race.py
Touch when:   never for a new repository; the override's variables change name, or another process
              starts under it.
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.server.auth import LOCAL_ISSUER
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.settings import ALLOW_UNSEALED_PROD_BY_ENV, ALLOW_UNSEALED_PROD_ENV
from crb.store.events import lock_event_writes
from crb.store.models import User

log = logging.getLogger(__name__)

#: The event every start under the override writes (``stage: system``).
ACTION = "posture.unsealed_override"
#: All of them on one trace, so an auditor reads the override's whole history in one place.
TRACE_ID = system_trace_id("posture", "unsealed_override")


class OverrideRefused(RuntimeError):
    """The override names no account, more than one, a non-admin or a deactivated admin."""


def _username(user: User) -> str:
    return user.subject.removeprefix("local:") if user.issuer == LOCAL_ISSUER else user.subject


def find_acknowledging_admin(db: Session, name: str) -> User:
    """The one active admin ``name`` identifies — a local username, an identity-provider
    subject or an email (case-insensitive) — or :class:`OverrideRefused` saying why not."""
    wanted = name.strip()
    folded = wanted.casefold()
    matches = [
        u
        for u in db.execute(select(User)).scalars()
        if wanted and (_username(u) == wanted or (u.email and u.email.casefold() == folded))
    ]
    where = f"{ALLOW_UNSEALED_PROD_BY_ENV}={wanted!r}"
    if not matches:
        raise OverrideRefused(
            f"{where} names no account; name an active admin, who owns the decision to run "
            f"production unsealed ({ALLOW_UNSEALED_PROD_ENV}, ADR-0023)"
        )
    if len(matches) > 1:
        raise OverrideRefused(f"{where} names {len(matches)} accounts; use the local username")
    (user,) = matches
    if user.role != "admin":
        raise OverrideRefused(
            f"{where} names a {user.role}; only an admin may set {ALLOW_UNSEALED_PROD_ENV}"
        )
    if not user.active:
        raise OverrideRefused(f"{where} names an admin who is deactivated")
    return user


def record_unsealed_override(
    factory: sessionmaker[Session],
    *,
    by: str,
    reason: str,
    process: str,
    posture: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Check ``by`` and write the start's ``posture.unsealed_override`` event; returns what
    was recorded. Raises :class:`OverrideRefused` (nothing written) when ``by`` is not one
    active admin — the caller must not start."""
    with factory() as db:
        # the events write lock first: every start writes this one trace, and two processes
        # starting at once must not read one ``seq`` (P-241 — the API and a worker, or two
        # replicas, at the same moment; the second insert would break (trace_id, seq))
        lock_event_writes(db)
        user = find_acknowledging_admin(db, by)
        payload: dict[str, Any] = {
            "username": _username(user),
            "reason": reason,
            "process": process,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "override": ALLOW_UNSEALED_PROD_ENV,
            "adr": "0023",
            **{k: posture[k] for k in sorted(posture)},
            **dict(extra or {}),
        }
        ev = append_system_event(
            db, trace_id=TRACE_ID, action=ACTION, actor=user.id, payload=payload
        )
        db.commit()
    log.warning(
        "%s: production starts under the unsealed override, set by %s (%s)",
        process,
        payload["username"],
        reason,
    )
    return {"event_id": ev.event_id, "actor": user.id, **payload}


__all__ = [
    "ACTION",
    "TRACE_ID",
    "OverrideRefused",
    "find_acknowledging_admin",
    "record_unsealed_override",
]
