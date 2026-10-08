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
              never for a product line, an empty statement or an act dated outside its
              bounds (after the day after UTC's today, before the withdrawal it follows or an
              observed install); that a product line is proven only by what was measured (a
              repository in its latest docker posture, the worker's stamp on its last run),
              never by a setting; that only an admin's reading names local admins; and the
              counts the platform stream serves.
How:          ``init_db`` on the parametrised backend; ``Settings`` built in-process; a health
              body and a ledger body passed as the routes pass them.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md
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

from crb.core.qualify import Qualification
from crb.server import golive
from crb.server.flow_record import record_install
from crb.server.routes.admin import user_trace_id
from crb.server.routes.runs import append_system_event
from crb.server.settings import Settings
from crb.store import qualifications as sq
from crb.store.db import init_db
from crb.store.models import Repo, Run, User

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
    "posture": {
        "env": "prod",
        "sealed": True,
        "sandbox_executor": "docker",
        "builder_executor": "docker",
        "factory_builds": "refused",
    },
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
    backend: Backend,
    *,
    executor: str = "docker",
    state: str = "qualified",
    posture: str = "1",
    qid: str = "q-1",
    repo: bool = True,
) -> None:
    with backend.factory() as s:
        if repo:
            s.add(Repo(name="calc", language="go", runner="go", config_json={"language": "go"}))
            s.commit()
        sq.append(
            s,
            Qualification(
                qualification_id=qid,
                repo="calc",
                task_id="a" * 40,
                posture_id="pst_" + posture * 24,
                posture={"executor": executor, "posture_class": f"{executor}/copy/sealed"},
                state=state,
                code="" if state == "qualified" else "QUAL_ENV_UNLOADABLE",
            ),
        )


def seed_stamped_run(backend: Backend, *, executor: str = "docker", **extra: Any) -> None:
    """A run the worker stamped: where its tests ran, and any unsealed override it carried."""
    with backend.factory() as s:
        if s.get(Repo, "calc") is None:
            s.add(Repo(name="calc", language="go", runner="go", config_json={"language": "go"}))
        s.add(
            Run(
                id="r" * 32,
                repo="calc",
                kind="replay",
                apparatus_json={"executor": {"executor": executor}, **extra},
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


def test_a_production_deployment_proves_all_six_product_lines(
    backend: Backend, tmp_path: Path
) -> None:
    init_db(backend.engine)
    seed_production_sign_in(backend)
    seed_sealed_repo(backend)
    seed_stamped_run(backend)
    st = settings(tmp_path, local_auth_enabled=False)
    got = states(read(backend, st))
    assert [k for k, v in got.items() if v == golive.PROVEN] == [
        "health-green",
        "dev-autologin-off",
        "ledger-verified",
        "sign-in",
        "repos-qualified",
        "sealed-posture",
    ]
    assert {v for k, v in got.items() if golive.LINES_BY_ID[k].proves == golive.BY_OPERATOR} == {
        golive.UNPROVEN
    }


def test_automatic_sign_in_on_leaves_its_line_unproven_and_names_no_account(
    backend: Backend, tmp_path: Path
) -> None:
    """The sign-in route acts on the API process's own setting, so the product reads that
    setting — never an admin's word for it — and an admin cannot attest the line while it is
    on (ADR-0027, ADR-0031)."""
    init_db(backend.engine)
    r = read(backend, settings(tmp_path, auth={"dev_autologin": "ada"}))
    assert states(r)["dev-autologin-off"] == golive.UNPROVEN
    why = detail(r, "dev-autologin-off")
    assert "automatic sign-in is on in this API process" in why and "ada" not in why
    assert states(read(backend, settings(tmp_path)))["dev-autologin-off"] == golive.PROVEN
    with backend.factory() as s, pytest.raises(golive.ProvenByProduct):
        golive.attest(
            s,
            "dev-autologin-off",
            actor="a",
            by="A",
            statement="crb doctor reads off",
            performed_on=TODAY,
            today=TODAY,
        )


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
    # a health reading with no probes — none served, or none readable — proves nothing
    # (deploy-and-go-live.truth.4: a line the product can read is proven only by its check)
    for unreadable in ({}, {"probes": []}, {"probes": ["not a probe"]}):
        r = read(backend, settings(tmp_path), health=unreadable)
        assert states(r)["health-green"] == golive.UNPROVEN, unreadable
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
    # the honesty floor: an intact chain with a false-Q1 on it is not a verified ledger
    fq1 = {
        **LEDGER_OK,
        "ok": False,
        "chain_ok": True,
        "broken_at": None,
        "false_q1_total": 1,
        "detail": "",
    }
    r = read(backend, settings(tmp_path), ledger=fq1)
    assert states(r)["ledger-verified"] == golive.UNPROVEN
    assert "false-Q1 = 1" in detail(r, "ledger-verified")


def test_sign_in_names_every_part_that_does_not_hold(backend: Backend, tmp_path: Path) -> None:
    init_db(backend.engine)
    with backend.factory() as s:
        s.add(User(id="r" * 32, subject="local:root", issuer="local", role="admin"))
        s.commit()
    st = settings(
        tmp_path, bootstrap_admin={"username": "root", "password": "correct-horse-battery"}
    )
    r = read(backend, st, oidc_enabled=False, names=True)
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
    # an organisation account that exists but has never signed in is no live proof either
    with backend.factory() as s:
        s.add(User(id="o" * 32, subject="sub-2", issuer="https://idp", role="viewer"))
        s.commit()
    assert "no organisation account has signed in yet" in detail(
        read(backend, st, oidc_enabled=True), "sign-in"
    )


def test_only_an_admin_reading_is_told_the_local_admins_by_name(
    backend: Backend, tmp_path: Path
) -> None:
    """The lowest role reads how many local admins are stale, never their login names:
    ``GET /users`` refuses it those names, so the go-live reading must not hand them over."""
    init_db(backend.engine)
    with backend.factory() as s:
        s.add(User(id="r" * 32, subject="local:root", issuer="local", role="admin"))
        s.commit()
    hidden = detail(read(backend, settings(tmp_path)), "sign-in")
    assert "root" not in hidden
    assert "1 active local admin has never had its password set since it was created" in hidden
    shown = detail(read(backend, settings(tmp_path), names=True), "sign-in")
    assert "never had its password set since it was created: root" in shown


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


def test_a_task_qualified_only_in_an_older_posture_does_not_prove_the_repository(
    backend: Backend, tmp_path: Path
) -> None:
    """The posture moved (a new image, say) and nothing qualifies in it yet: the gate refuses
    every task (ADR-0019), so the line cannot read proven on the old posture's record."""
    init_db(backend.engine)
    seed_sealed_repo(backend, posture="1", qid="q-1")
    assert states(read(backend, settings(tmp_path)))["repos-qualified"] == golive.PROVEN
    seed_sealed_repo(backend, posture="2", qid="q-2", state="unqualified", repo=False)
    r = read(backend, settings(tmp_path))
    assert states(r)["repos-qualified"] == golive.UNPROVEN
    assert "calc (no task qualified in pst_2222" in detail(r, "repos-qualified")


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
    assert detail(r, "sealed-posture").startswith("tests run local, the builder runs host")


def test_the_sealed_posture_is_measured_not_only_configured(
    backend: Backend, tmp_path: Path
) -> None:
    """A configuration that says docker is not a measurement: the line needs the worker's own
    stamp on a run, and a factory build on the host is the builder unsealed (ADR-0023)."""
    init_db(backend.engine)
    # configured sealed, but no run has recorded where it ran
    r = read(backend, settings(tmp_path))
    assert states(r)["sealed-posture"] == golive.UNPROVEN
    assert "no run has recorded where it ran yet" in detail(r, "sealed-posture")
    seed_stamped_run(backend)
    assert states(read(backend, settings(tmp_path)))["sealed-posture"] == golive.PROVEN
    # factory builds run the builder on the host: the builder is not sealed
    host = {**GREEN_HEALTH, "posture": {**GREEN_HEALTH["posture"], "factory_builds": "host"}}
    r = read(backend, settings(tmp_path), health=host)
    assert states(r)["sealed-posture"] == golive.UNPROVEN
    assert "a factory build runs its builder on the host" in detail(r, "sealed-posture")


def test_a_run_stamped_unsealed_leaves_the_sealed_posture_unproven(
    backend: Backend, tmp_path: Path
) -> None:
    init_db(backend.engine)
    seed_stamped_run(backend, executor="local", unsealed_prod_override={"builder_executor": "host"})
    why = detail(read(backend, settings(tmp_path)), "sealed-posture")
    assert "ran its tests local" in why and "under the unsealed override" in why


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
                performed_on=TODAY + _dt.timedelta(days=2),
                today=TODAY,
            )
        assert golive.attestations(s) == {}


def test_the_day_east_of_utc_is_not_the_future(backend: Backend) -> None:
    """An admin in Sydney at 08:00 on the 28th records an act done that morning: in UTC it is
    still the 27th. No place on Earth is more than a day ahead of UTC, so the 28th is today
    somewhere and is accepted; the 29th is the future everywhere."""
    init_db(backend.engine)
    with backend.factory() as s:
        golive.attest(
            s,
            "doctor",
            actor="a",
            by="A",
            statement="both hosts ok",
            performed_on=TODAY + _dt.timedelta(days=1),
            today=TODAY,
        )
        s.commit()
        assert golive.attestations(s)["doctor"].performed_on == "2026-09-28"


def test_an_act_cannot_be_dated_before_the_withdrawal_it_follows_or_the_install(
    backend: Backend,
) -> None:
    """A restore rehearsed on 1 September, withdrawn when a later restore failed, cannot be
    re-attested on the same 1 September rehearsal; nor can any act predate the deployment."""
    init_db(backend.engine)
    first = _dt.date(2026, 9, 1)
    with backend.factory() as s:
        golive.attest(
            s,
            "backups-pitr",
            actor="a",
            by="A",
            statement="restore rehearsed; chain verified",
            performed_on=first,
            today=TODAY,
        )
        golive.withdraw(s, "backups-pitr", actor="a", by="A")
        s.commit()
        with pytest.raises(ValueError, match="withdrawn on"):
            golive.attest(
                s,
                "backups-pitr",
                actor="a",
                by="A",
                statement="restore rehearsed; chain verified",
                performed_on=first,
            )
        # a fresh rehearsal after the withdrawal is accepted
        golive.attest(
            s,
            "backups-pitr",
            actor="a",
            by="A",
            statement="restore rehearsed again; chain verified",
            performed_on=_dt.datetime.now(_dt.UTC).date(),
        )
        record_install(s, fresh=True)
        s.commit()
        with pytest.raises(ValueError, match="installed on"):
            golive.attest(
                s,
                "doctor",
                actor="a",
                by="A",
                statement="ran it",
                performed_on=_dt.date(1900, 1, 1),
            )


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
