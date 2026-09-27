"""crb.server.golive — each go-live line proven, attested or unproven, never ticked by belief.

Navigation
----------
What it is:   The unit tests of the go-live reading: the lines, the five product checks and
              the attestation record, on both store dialects.
What it does: Pins that every line of docs/DEPLOYMENT.md §8 is in ``LINES`` with who proves it
              and that the guide marks it the same way; that each product check proves its
              line only when the facts hold and names what failed otherwise; that an operator
              line reads attested only after a recorded attestation (who, the day it was done,
              the day it was recorded, what was done), unproven again after a withdrawal, and
              never for a product line, an empty statement or an act dated tomorrow; and the
              counts the platform stream serves.
How:          ``init_db`` on the parametrised backend; ``Settings`` built in-process; a health
              body and a ledger body passed as the routes pass them.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0045-go-live-lines-are-proven-or-attested.md
Works with:   src/crb/server/golive.py (under test), docs/DEPLOYMENT.md (the §8 markers),
              tests/conftest_store.py (the backends)
Tested by:    tests/test_golive.py
Touch when:   never for a new repository; a go-live line or a product check changes.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from crb.server import golive
from crb.server.routes.admin import user_trace_id
from crb.server.routes.runs import append_system_event
from crb.server.settings import Settings
from crb.store.db import init_db
from crb.store.models import Repo, TaskQualification, User

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
TODAY = _dt.date(2026, 9, 27)

GREEN_HEALTH: dict[str, Any] = {
    "status": "ok",
    "probes": [
        {"name": "db", "status": "ok", "detail": "", "data": {}},
        {"name": "ledger", "status": "ok", "detail": "", "data": {}},
        {"name": "sandbox", "status": "skipped", "detail": "", "data": {}},
        {"name": "provision", "status": "skipped", "detail": "", "data": {}},
    ],
    "posture": {"sealed": True, "sandbox_executor": "docker", "builder_executor": "docker"},
}
LEDGER_OK: dict[str, Any] = {
    "ok": True,
    "rows": 3,
    "false_q1_total": 0,
    "chain_ok": True,
    "broken_at": None,
    "detail": "3 rows, chain intact, false_q1=0",
}


def settings(tmp_path: Path, **kw: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "dev",
        "home": tmp_path,
        "secret_key": SecretStr("s" * 40),
        "log_format": "text",
    }
    base.update(kw)
    return Settings(**base)


def states(reading: golive.GoLiveReading) -> dict[str, str]:
    return {ls.line.id: ls.state for ls in reading.lines}


def detail(reading: golive.GoLiveReading, line: str) -> str:
    return next(ls.detail for ls in reading.lines if ls.line.id == line)


def read(backend: Backend, st: Settings, **kw: Any) -> golive.GoLiveReading:
    args: dict[str, Any] = {"health": GREEN_HEALTH, "ledger": LEDGER_OK, "oidc_enabled": True}
    args.update(kw)
    with backend.factory() as s:
        return golive.evaluate(s, st, **args)


def seed_production_sign_in(backend: Backend) -> None:
    """An organisation account that has signed in, and a local admin whose password was set."""
    with backend.factory() as s:
        s.add(
            User(
                id="u" * 32,
                subject="sub-1",
                issuer="https://idp",
                role="admin",
                last_login="2026-09-20T10:00:00+00:00",
            )
        )
        s.add(User(id="r" * 32, subject="local:root", issuer="local", role="admin"))
        append_system_event(
            s,
            trace_id=user_trace_id("r" * 32),
            action="user.password_set",
            actor="u" * 32,
            payload={"target": "r" * 32, "by": "admin"},
        )
        s.commit()


def seed_sealed_repo(
    backend: Backend, *, executor: str = "docker", state: str = "qualified"
) -> None:
    with backend.factory() as s:
        s.add(Repo(name="calc", language="go", runner="go", config_json={"language": "go"}))
        s.add(
            TaskQualification(
                qualification_id="q-1",
                repo="calc",
                task_id="a" * 40,
                posture_id="pst_" + "1" * 24,
                posture_class=f"{executor}/copy/sealed",
                executor=executor,
                state=state,
                code="" if state == "qualified" else "QUAL_ENV_UNLOADABLE",
                body_json={},
            )
        )
        s.commit()


# --- the lines and the guide -----------------------------------------------------------


def test_every_line_of_the_guide_is_a_line_here_and_marked_the_same_way() -> None:
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    section = text.split("## 8. Go-live checklist", 1)[1].split("\n## 9.", 1)[0]
    marked = dict(
        re.findall(r"- \[ \] \*\*`([a-z0-9-]+)`\*\* · (product proves|operator attests)", section)
    )
    assert set(marked) == set(golive.LINES_BY_ID), (
        "DEPLOYMENT §8 and golive.LINES must list the same lines"
    )
    for line in golive.LINES:
        want = "product proves" if line.proves == golive.BY_PRODUCT else "operator attests"
        assert marked[line.id] == want, line.id
        assert line.source and line.doc


def test_the_acts_the_product_does_not_perform_are_operator_lines() -> None:
    # run-the-platform's non-goals: egress, backups, digest pinning, alerts, penetration test
    for line in (
        "egress-denied",
        "backups-pitr",
        "image-digest",
        "false-q1-alert",
        "penetration-test",
    ):
        assert golive.LINES_BY_ID[line].proves == golive.BY_OPERATOR


# --- the product checks ----------------------------------------------------------------


def test_a_production_deployment_proves_all_five_product_lines(
    backend: Backend, tmp_path: Path
) -> None:
    init_db(backend.engine)
    seed_production_sign_in(backend)
    seed_sealed_repo(backend)
    st = settings(tmp_path, local_auth_enabled=False)
    got = states(read(backend, st))
    assert [k for k, v in got.items() if v == golive.PROVEN] == [
        "health-green",
        "ledger-verified",
        "sign-in",
        "repos-qualified",
        "sealed-posture",
    ]
    assert {v for k, v in got.items() if golive.LINES_BY_ID[k].proves == golive.BY_OPERATOR} == {
        golive.UNPROVEN
    }


def test_a_degraded_probe_leaves_the_health_line_unproven_and_names_it(
    backend: Backend, tmp_path: Path
) -> None:
    init_db(backend.engine)
    health = {
        **GREEN_HEALTH,
        "probes": [*GREEN_HEALTH["probes"], {"name": "worker", "status": "degraded"}],
    }
    r = read(backend, settings(tmp_path), health=health)
    assert states(r)["health-green"] == golive.UNPROVEN
    assert "worker is degraded" in detail(r, "health-green")
    r = read(backend, settings(tmp_path), health={})
    assert detail(r, "health-green") == "the health check could not be read"


def test_a_broken_chain_or_an_unread_ledger_is_unproven(backend: Backend, tmp_path: Path) -> None:
    init_db(backend.engine)
    broken = {**LEDGER_OK, "ok": False, "chain_ok": False, "broken_at": 7}
    assert (
        detail(read(backend, settings(tmp_path), ledger=broken), "ledger-verified")
        == "the chain is broken at seq 7"
    )
    r = read(backend, settings(tmp_path), ledger=None)
    assert states(r)["ledger-verified"] == golive.UNPROVEN
    assert "could not be read" in detail(r, "ledger-verified")


def test_sign_in_names_every_part_that_does_not_hold(backend: Backend, tmp_path: Path) -> None:
    init_db(backend.engine)
    with backend.factory() as s:
        s.add(User(id="r" * 32, subject="local:root", issuer="local", role="admin"))
        s.commit()
    st = settings(
        tmp_path, bootstrap_admin={"username": "root", "password": "correct-horse-battery"}
    )
    r = read(backend, st, oidc_enabled=False)
    why = detail(r, "sign-in")
    assert states(r)["sign-in"] == golive.UNPROVEN
    for part in (
        "OpenID Connect is not configured",
        "local sign-in is on",
        "CRB_BOOTSTRAP_ADMIN__* is still set",
        "never had its password set since it was created: root",
    ):
        assert part in why
    # configured, but nobody has signed in through it: not yet live
    assert "no organisation account has signed in yet" in detail(
        read(backend, st, oidc_enabled=True), "sign-in"
    )


def test_repos_must_each_qualify_in_a_docker_posture(backend: Backend, tmp_path: Path) -> None:
    init_db(backend.engine)
    assert (
        detail(read(backend, settings(tmp_path)), "repos-qualified")
        == "no repository is connected yet"
    )
    seed_sealed_repo(backend, executor="local")
    r = read(backend, settings(tmp_path))
    assert states(r)["repos-qualified"] == golive.UNPROVEN
    assert "1 of 1 repositories have no task qualified in the sealed posture: calc" in detail(
        r, "repos-qualified"
    )
    down = {
        **GREEN_HEALTH,
        "probes": [{"name": "provision", "status": "down", "detail": "store not visible"}],
    }
    assert "provisioning is down: store not visible" in detail(
        read(backend, settings(tmp_path), health=down), "repos-qualified"
    )


def test_an_unsealed_posture_is_unproven_with_both_executors(
    backend: Backend, tmp_path: Path
) -> None:
    init_db(backend.engine)
    health = {
        **GREEN_HEALTH,
        "posture": {"sealed": False, "sandbox_executor": "local", "builder_executor": "host"},
    }
    r = read(backend, settings(tmp_path), health=health)
    assert states(r)["sealed-posture"] == golive.UNPROVEN
    assert detail(r, "sealed-posture") == "tests run local, the builder runs host"


# --- the attestation record -------------------------------------------------------------


def test_an_attestation_names_who_when_and_what_and_a_withdrawal_undoes_it(
    backend: Backend, tmp_path: Path
) -> None:
    init_db(backend.engine)
    with backend.factory() as s:
        golive.attest(
            s,
            "egress-denied",
            actor="a" * 32,
            by="Ada Admin",
            statement="  curl  to 1.1.1.1 from worker-0 timed out ",
            performed_on=_dt.date(2026, 9, 25),
            today=TODAY,
        )
        s.commit()
    r = read(backend, settings(tmp_path))
    line = next(ls for ls in r.lines if ls.line.id == "egress-denied")
    assert line.state == golive.ATTESTED and line.attestation is not None
    a = line.attestation.to_dict()
    assert (a["by"], a["actor"], a["performed_on"], a["statement"]) == (
        "Ada Admin",
        "a" * 32,
        "2026-09-25",
        "curl to 1.1.1.1 from worker-0 timed out",
    )
    assert a["recorded_at"][:2] == "20" and "Ada Admin recorded on" in line.detail
    with backend.factory() as s:
        golive.withdraw(s, "egress-denied", actor="a" * 32, by="Ada Admin")
        s.commit()
    assert states(read(backend, settings(tmp_path)))["egress-denied"] == golive.UNPROVEN
    with backend.factory() as s, pytest.raises(golive.NotAttested):
        golive.withdraw(s, "egress-denied", actor="a" * 32, by="Ada Admin")


def test_nothing_ticks_a_line_by_belief(backend: Backend) -> None:
    init_db(backend.engine)
    with backend.factory() as s:
        with pytest.raises(golive.ProvenByProduct):
            golive.attest(
                s,
                "health-green",
                actor="a",
                by="A",
                statement="it was green",
                performed_on=TODAY,
                today=TODAY,
            )
        with pytest.raises(golive.UnknownLine):
            golive.attest(
                s, "made-up", actor="a", by="A", statement="x", performed_on=TODAY, today=TODAY
            )
        with pytest.raises(ValueError, match="empty"):
            golive.attest(
                s, "doctor", actor="a", by="A", statement="   ", performed_on=TODAY, today=TODAY
            )
        with pytest.raises(ValueError, match="future"):
            golive.attest(
                s,
                "doctor",
                actor="a",
                by="A",
                statement="ran it",
                performed_on=TODAY + _dt.timedelta(days=1),
                today=TODAY,
            )
        assert golive.attestations(s) == {}


def test_the_counts_add_up_to_the_lines(backend: Backend, tmp_path: Path) -> None:
    init_db(backend.engine)
    with backend.factory() as s:
        golive.attest(
            s,
            "doctor",
            actor="a",
            by="A",
            statement="both hosts ok",
            performed_on=TODAY,
            today=TODAY,
        )
        s.commit()
    c = read(backend, settings(tmp_path)).counts()
    assert c["lines"] == len(golive.LINES) == c["proven"] + c["attested"] + c["unproven"]
    assert c["attested"] == 1
