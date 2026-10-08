"""Evidence and import governance — the audit's stream B findings as regression tests.

EI-2: one admin turned fabricated JSONL rows into an active, route-``deliver`` sign-off —
``POST /ledger/import`` kept the file's ``actor``, ``provenance`` and ``oracle_strength``,
wrote no audit event, and the sign-off counted the rows, read their oracle number and
accepted an attestation of a row whose pack exists nowhere. Now every imported row is
stamped inside its hashed body (``provenance`` ``imported:ledger``, ``actor`` ``import``,
who and when, the source values kept in labels), the import is a ``ledger.imported`` event,
and the sign-off and routing reads count only rows measured here and read the oracle from
the ``oracle.score`` events alone.

EI-3: ``_RunLedger.append`` appended a clean row whose pack was missing, forged or could not
be stored; now the row is written demoted (``harness``, the reason in ``error``) and
``/ledger/verify`` counts a measured clean row whose stored pack is absent or does not
re-hash to its name.

EI-6: nothing on the server walked the sign-off or the review chain; now ``/ledger/verify``,
``GET /signoffs/verify`` and the ``ledger`` probe of ``/health`` do, and a tampered sign-off
is served inactive and lifts no cell. The skeptic's pass found the first fix failed closed per
ROW, so re-scoping a revocation revived the licence it withdrew, and that the tamper test read
a projection a full-cell sign-off never lifts; now a broken chain lifts nothing anywhere
(DL-079) and every licence assertion reads ``/routes``' full cell, lifted first.

EI-2 residual: a reader's view (an explicit apparatus or ``all``) routes imported rows; every
cell and decision now names them (``rows_imported``).

Navigation
----------
What it is:   The regression tests for the audit's evidence-and-import findings EI-2, EI-3 and
              EI-6 and the skeptic's follow-up (docs/PREVENTION.md P-202..P-206, P-207).
What it does: Replays the skeptic's end-to-end (fabricated rows imported → sign-off → route
              deliver) and pins that the sign-off is now refused with a named reason, that
              imported rows are stamped and audited and never enter a licensing read, and that
              a row's own oracle number is never read; drives the worker's ``_RunLedger`` with
              a missing, a forged and an unstorable pack; tampers a sign-off, a revocation and
              a review row under the triggers, reads the break from every verifier and pins
              that the full cell the delivery gate reads is lifted before and not after.
How:          ``make_env`` over the seed (``tests/fixtures/server_seed.py``) with the sign-off
              helpers (``tests/fixtures/signoff_seed.py``); rows cloned from the seed's
              accepted rows; the worker's ``_RunLedger`` with a stub run context; tampering
              through raw SQL after dropping the table's append-only trigger, as only the
              tables' owner can (an ``INSERT OR REPLACE`` is refused since EI-5, DL-081).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md,
              docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
Works with:   src/crb/server/routes/ledger.py (import, verify), src/crb/store/ledger.py
              (``import_rows``), src/crb/core/ledger.py (``rows_measured_here``),
              src/crb/server/routes/signoffs.py (``cell_rows``, ``resolve_attestation``,
              ``verify_signoffs``, ``signoff_chain_intact``, ``load_signoff_records``),
              src/crb/core/capability.py (``rows_imported``), src/crb/server/worker.py
              (``_RunLedger``), src/crb/server/routes/system.py (the ``ledger`` probe)
Tested by:    tests/test_evidence_import_governance.py
Touch when:   onboarding a client repository never needs it; the import stamp, the licensing
              read or a verifier changes — the refusal names asserted here are what an
              auditor reads.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import CELL_FIELDS, GradeRow
from crb.core.version import APPARATUS_VERSION
from crb.server.app import API_PREFIX
from crb.server.worker import _RunLedger
from crb.store.ledger import DbLedger
from crb.store.models import Event, EvidencePackRow, Grade, Signoff
from fixtures.server_seed import ALPHA, DELIVER_CELL, Env, envelope, login, make_env, user_id
from fixtures.signoff_seed import (
    STATEMENT,
    accepted_row,
    attested_body,
    clear_policy,
    pass_controls,
)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


LARGE_CELL = {**DELIVER_CELL, "size": "L"}
#: The seed's deliver cell as ``/routes`` labels it (the full seven-field key).
_DELIVER_LABEL = "|".join(DELIVER_CELL[f] for f in CELL_FIELDS)


def _hex(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _fabricated(env: Env, n: int = 40, *, size: str = "L") -> list[GradeRow]:
    """The skeptic's forgery: ``n`` clones of the seed's newest clean ``bug.fix|S`` row with
    fresh task and row ids, a person's name as ``actor``, no run, no source hash, an oracle
    strength of 0.97 and packs that exist nowhere."""
    src = accepted_row(env, DELIVER_CELL).to_dict()
    out: list[GradeRow] = []
    for i in range(n):
        d = dict(src)
        d.update(
            size=size,
            task_id=_hex(f"fab-task-{size}-{i}")[:40],
            row_id=f"fab-{size}-{i}",
            actor="alice",
            run_id="",
            prev_hash="",
            row_hash="",
            oracle_strength=0.97,
            evidence_pack_hash=_hex(f"nowhere-{size}-{i}"),
        )
        out.append(GradeRow.from_dict(d))
    return out


def _jsonl(rows: list[GradeRow]) -> bytes:
    return "".join(json.dumps(r.to_dict(), sort_keys=True) + "\n" for r in rows).encode()


def _import(env: Env, rows: list[GradeRow], name: str = "forged.jsonl") -> Any:
    return env.client.post(
        f"{API_PREFIX}/ledger/import",
        files={"file": (name, _jsonl(rows), "application/x-ndjson")},
    )


def _events(env: Env, action: str) -> list[Event]:
    with env.factory() as s:
        return list(s.execute(select(Event).where(Event.action == action)).scalars())


# ---------------------------------------------------------------------------
# EI-2 — imported rows never license anything by themselves
# ---------------------------------------------------------------------------


class TestImportedRowsNeverLicense:
    def test_the_skeptics_end_to_end_is_refused_at_the_sign_off_with_a_named_reason(
        self, env: Env
    ) -> None:
        pass_controls(env)
        forged = _fabricated(env)
        r = _import(env, forged)
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 40 and r.json()["source_chain_ok"] is False
        target = next(
            g
            for g in env.get("/grades?repo=alpha&limit=500").json()["items"]
            if g["row_id"] == "fab-L-0"
        )
        body = {
            "repo": ALPHA,
            "cell": LARGE_CELL,
            "note": "forged",
            "attestation": {"reviewed_row_hash": target["row_hash"], "statement": STATEMENT},
        }
        r = env.post("/signoffs", json=body)
        assert r.status_code == 409, r.text
        e = envelope(r)
        assert e["code"] == "signoff_refused"
        assert e["detail"]["code"] == "attested_row_not_measured"
        assert "imported" in e["message"]
        refused = _events(env, "signoff.refused")
        assert refused and refused[-1].payload_json["code"] == "attested_row_not_measured"
        # nothing was written, and no cell was lifted
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 0
        # the preview names the same refusal before anyone tries
        q = "&".join(f"{k}={v}" for k, v in LARGE_CELL.items())
        r = env.get(f"/signoffs/preview?repo={ALPHA}&{q}&reviewed_row_hash={target['row_hash']}")
        assert r.status_code == 409 and envelope(r)["detail"]["code"] == "attested_row_not_measured"
        # without an attestation the cell has no evidence at all: imported rows never count
        p = env.get(f"/signoffs/preview?repo={ALPHA}&{q}").json()
        assert p["evidence"]["n"] == 0 and p["signable"] is False
        assert p["accepted_rows"] == []
        # and the routing read that licenses delivery never sees them either
        cells = env.get(f"/capability-map?repo={ALPHA}").json()["cells"]
        assert not [c for c in cells if c["capability_class"] == "bug.fix" and c["size"] == "L"]
        routes = env.get(f"/routes?repo={ALPHA}").json()["decisions"]
        assert not [d for d in routes if d["cell"]["size"] == "L"]

    def test_a_readers_view_names_the_imported_rows_behind_every_cell_and_route(
        self, env: Env
    ) -> None:
        """The skeptic's EI-2 residual: under a named apparatus version (history) imported rows
        are read. That view licenses nothing, but it must say whose evidence it is: every cell
        and every route decision carries ``rows_imported`` beside ``rows``. ``all`` pools two
        apparatus versions and is refused outright (ADR-0025 item 1)."""
        pass_controls(env)
        assert _import(env, _fabricated(env)).status_code == 200
        for path in ("capability-map", "routes"):
            refused = env.get(f"/{path}?repo={ALPHA}&apparatus=all")
            assert refused.status_code == 422, refused.text
            assert refused.json()["error"]["code"] == "apparatus_pooling_refused"
        for view in (APPARATUS_VERSION,):
            cells = env.get(f"/capability-map?repo={ALPHA}&apparatus={view}").json()["cells"]
            large = next(
                c for c in cells if c["capability_class"] == "bug.fix" and c["size"] == "L"
            )
            assert large["rows_imported"] == large["rows"] == 40
            small = next(
                c for c in cells if c["capability_class"] == "bug.fix" and c["size"] == "S"
            )
            assert small["rows_imported"] == 0 and small["rows"] > 0
            decisions = env.get(f"/routes?repo={ALPHA}&apparatus={view}").json()["decisions"]
            fab = next(d for d in decisions if d["cell"]["size"] == "L")
            assert fab["rows_imported"] == 40
            assert next(d for d in decisions if d["label"] == _DELIVER_LABEL)["rows_imported"] == 0
        # the licensing reading never sees them, so it has none to name
        cur = env.get(f"/routes?repo={ALPHA}").json()["decisions"]
        assert cur and all(d["rows_imported"] == 0 for d in cur)

    def test_every_imported_row_is_stamped_inside_its_hashed_body(self, env: Env) -> None:
        forged = _fabricated(env, 3)
        raw = _jsonl(forged)
        r = env.client.post(
            f"{API_PREFIX}/ledger/import", files={"file": ("f.jsonl", raw, "application/x-ndjson")}
        )
        assert r.status_code == 200, r.text
        rows = [
            GradeRow.from_dict(g)
            for g in env.get(f"/grades?repo={ALPHA}&limit=500").json()["items"]
            if g["row_id"].startswith("fab-")
        ]
        assert len(rows) == 3
        admin = user_id("root")
        for row, src in zip(sorted(rows, key=lambda x: x.row_id), forged, strict=True):
            assert row.provenance == "imported:ledger"
            assert row.actor == "import"
            assert row.labels["imported_by"] == admin
            assert row.labels["imported_at"]
            assert row.labels["source_row_hash"] == ""  # always present, empty when absent
            assert row.labels["source_actor"] == "alice"
            assert row.labels["source_provenance"] == "measured"
            assert row.labels["import_sha256"] == hashlib.sha256(raw).hexdigest()
            assert row.verify_hash()  # the stamp is inside the hash
            assert row.oracle_strength == src.oracle_strength  # kept, never read to license
        assert env.get("/ledger/verify").json()["ok"] is True

    def test_the_import_is_one_audit_event_naming_who_what_and_the_source_chain(
        self, env: Env
    ) -> None:
        raw = _jsonl(_fabricated(env, 2))
        env.client.post(
            f"{API_PREFIX}/ledger/import", files={"file": ("f.jsonl", raw, "application/x-ndjson")}
        )
        [ev] = _events(env, "ledger.imported")
        p = ev.payload_json
        assert ev.actor == user_id("root") and ev.stage == "system"
        assert p["file_sha256"] == hashlib.sha256(raw).hexdigest()
        assert p["read"] == 2 and p["imported"] == 2 and p["skipped"] == 0
        assert p["source_chain_ok"] is False
        assert "re-chained" in p["note"] and p["provenance"] == ["imported:ledger"]
        assert p["repos"] == [ALPHA]

    def test_a_row_measured_here_never_lends_the_cell_its_own_oracle_number(self, env: Env) -> None:
        """A row stamped ``measured`` that carries an oracle strength (a pre-fix import) and
        whose tasks were never scored: the cell's oracle is unmeasured, not 0.97."""
        clear_policy(env)
        src = accepted_row(env, DELIVER_CELL).to_dict()
        ledger = DbLedger(env.factory)
        rows = []
        for i in range(12):
            d = dict(src)
            d.update(
                size="M",
                task_id=_hex(f"strong-{i}")[:40],
                row_id=f"strong-{i}",
                prev_hash="",
                row_hash="",
                oracle_strength=0.97,
            )
            rows.append(GradeRow.from_dict(d))
        ledger.append_many(rows)
        cell = {**DELIVER_CELL, "size": "M"}
        q = "&".join(f"{k}={v}" for k, v in cell.items())
        p = env.get(f"/signoffs/preview?repo={ALPHA}&{q}").json()
        assert p["evidence"]["n"] == 12
        assert p["evidence"]["oracle_strength"] is None
        assert "oracle_unmeasured" in {x["code"] for x in p["refusals"]}
        c = next(
            c
            for c in env.get(f"/capability-map?repo={ALPHA}").json()["cells"]
            if c["capability_class"] == "bug.fix" and c["size"] == "M"
        )
        assert c["oracle_strength_mean"] is None and c["route"] != "deliver"

    def test_an_attested_row_without_a_stored_verified_pack_is_refused(self, env: Env) -> None:
        clear_policy(env)
        body = attested_body(env, DELIVER_CELL)
        # forge the pack under the attested row's name: the body no longer hashes to it
        row = accepted_row(env, DELIVER_CELL)
        with env.factory() as s:
            s.execute(text("DROP TRIGGER IF EXISTS evidence_no_update"))
            s.execute(
                text("UPDATE evidence SET body_json = :b WHERE pack_hash = :h"),
                {
                    "b": json.dumps({"pack_hash": row.evidence_pack_hash, "grade": {}}),
                    "h": row.evidence_pack_hash,
                },
            )
            s.commit()
        r = env.post("/signoffs", json=body)
        assert r.status_code == 409, r.text
        assert envelope(r)["detail"]["code"] == "attested_row_without_pack"


# ---------------------------------------------------------------------------
# EI-3 — the worker never appends a clean row whose pack it cannot keep
# ---------------------------------------------------------------------------


class _Ctx:
    """The two things ``_RunLedger`` asks of a run context."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.counts: dict[str, Any] = {}

    def emit(self, stage: str, action: str, **payload: Any) -> None:
        self.events.append((stage, action, payload))


def _clean_clone(env: Env, tag: str, pack_hash: str) -> GradeRow:
    d = accepted_row(env, DELIVER_CELL).to_dict()
    d.update(row_id=f"w-{tag}", prev_hash="", row_hash="", evidence_pack_hash=pack_hash)
    return GradeRow.from_dict(d)


def _run_ledger(env: Env, evdir: Path, factory: Any = None) -> tuple[_RunLedger, _Ctx]:
    ctx = _Ctx()
    rl = _RunLedger(
        DbLedger(env.factory),
        factory or env.factory,
        evdir,
        ctx,
        "local",  # type: ignore[arg-type]
    )
    return rl, ctx


class TestWorkerKeepsNoCleanRowWithoutItsPack:
    def test_a_missing_pack_demotes_the_row(self, env: Env, tmp_path: Path) -> None:
        rl, ctx = _run_ledger(env, tmp_path / "ev")
        out = rl.append(_clean_clone(env, "missing", "1" * 64))
        assert out.clean is False and out.failure_kind == "harness"
        assert "evidence pack" in out.error
        assert ("ledger", "ledger.pack_missing") in [(a, b) for a, b, _ in ctx.events]
        assert env.get("/ledger/verify").json()["ok"] is True

    def test_a_forged_pack_is_never_stored_and_demotes_the_row(
        self, env: Env, tmp_path: Path
    ) -> None:
        evdir = tmp_path / "ev"
        evdir.mkdir()
        forged = "2" * 64
        (evdir / f"{forged}.json").write_text(json.dumps({"pack_hash": forged, "grade": {"x": 1}}))
        rl, ctx = _run_ledger(env, evdir)
        out = rl.append(_clean_clone(env, "forged", forged))
        assert out.clean is False and "does not hash to its name" in out.error
        with env.factory() as s:
            assert s.get(EvidencePackRow, forged) is None
        assert ("ledger", "ledger.pack_forged") in [(a, b) for a, b, _ in ctx.events]

    def test_a_pack_the_store_cannot_keep_demotes_the_row(self, env: Env, tmp_path: Path) -> None:
        evdir = tmp_path / "ev"
        evdir.mkdir()
        real = accepted_row(env, DELIVER_CELL).evidence_pack_hash
        body = DbLedger(env.factory).get_pack(real)
        (evdir / f"{real}.json").write_text(json.dumps(body))

        def _locked() -> Session:
            raise RuntimeError("db locked")

        rl, ctx = _run_ledger(env, evdir, factory=_locked)
        out = rl.append(_clean_clone(env, "store", real))
        assert out.clean is False and "could not be stored" in out.error
        assert ("ledger", "ledger.pack_store_error") in [(a, b) for a, b, _ in ctx.events]

    def test_an_authentic_pack_keeps_the_row_clean(self, env: Env, tmp_path: Path) -> None:
        evdir = tmp_path / "ev"
        evdir.mkdir()
        real = accepted_row(env, DELIVER_CELL).evidence_pack_hash
        (evdir / f"{real}.json").write_text(json.dumps(DbLedger(env.factory).get_pack(real)))
        rl, ctx = _run_ledger(env, evdir)
        out = rl.append(_clean_clone(env, "ok", real))
        assert out.clean is True and not ctx.events

    def test_verify_counts_a_measured_clean_row_whose_pack_is_absent_or_forged(
        self, env: Env
    ) -> None:
        ledger = DbLedger(env.factory)
        ledger.append(_clean_clone(env, "absent", "3" * 64))
        d = env.get("/ledger/verify").json()
        assert d["ok"] is False and d["clean_without_pack"] == 1
        forged = "4" * 64
        with env.factory() as s:
            s.add(
                EvidencePackRow(
                    pack_hash=forged, repo=ALPHA, task_id="t", run_id="", body_json={"x": 1}
                )
            )
            s.commit()
        ledger.append(_clean_clone(env, "forged", forged))
        d = env.get("/ledger/verify").json()
        assert d["clean_without_pack"] == 2 and "clean_without_pack=2" in d["detail"]


# ---------------------------------------------------------------------------
# EI-6 — the sign-off and review chains are verified on the server
# ---------------------------------------------------------------------------


def _drop_trigger(factory: sessionmaker[Session], table: str) -> None:
    with factory() as s:
        s.execute(text(f"DROP TRIGGER IF EXISTS {table}_no_update"))
        s.commit()


def _probe(env: Env, name: str) -> dict[str, Any]:
    body = env.get("/health").json()
    return next(p for p in body["probes"] if p["name"] == name)


def _tier(env: Env) -> str:
    """The seed's deliver cell's tier on ``/routes`` — the FULL cell projection, the one the
    worker's delivery gate reads (a class x size projection is never lifted by a sign-off on
    a full cell, so a tier read there could not tell a live licence from none)."""
    decisions = env.get(f"/routes?repo={ALPHA}").json()["decisions"]
    return str(next(d for d in decisions if d["label"] == _DELIVER_LABEL)["verification_tier"])


#: The skeptic's first route for moving the revocation row to another scope in place:
#: ``INSERT OR REPLACE`` on its own ``seq``. Stream C's EI-5 fix (recursive triggers on every
#: SQLite connection, DL-081) makes its implicit delete meet the append-only trigger, so it is
#: refused; the test pins that and then moves the row as the tables' owner could.
_REPLACE_REVOCATION = text(
    "INSERT OR REPLACE INTO signoffs (seq, signoff_id, repo, cell_json, tier, verifier, note,"
    " revoke, evidence_rows, created, prev_hash, row_hash)"
    " SELECT seq, signoff_id, repo, json_set(cell_json, '$.size', 'XL'), tier, verifier, note,"
    " revoke, evidence_rows, created, prev_hash, row_hash FROM signoffs WHERE revoke = 1"
)

#: The same move with the ``UPDATE`` trigger dropped first: the row's ``row_hash`` is left as
#: it was, so only a chain walk can see it.
_MOVE_REVOCATION = text(
    "UPDATE signoffs SET cell_json = json_set(cell_json, '$.size', 'XL') WHERE revoke = 1"
)


class TestSignoffAndReviewChainsAreVerified:
    def test_an_intact_store_verifies_every_chain(self, env: Env) -> None:
        clear_policy(env)
        assert env.post("/signoffs", json=attested_body(env, DELIVER_CELL)).status_code == 201
        d = env.get("/ledger/verify").json()
        assert d["ok"] is True
        assert d["signoffs"] == {
            "rows": 1,
            "chain_ok": True,
            "broken_at": None,
            "detail": "1 rows, chain intact",
        }
        assert d["reviews"]["chain_ok"] is True
        s = env.get("/signoffs/verify").json()
        assert s["ok"] is True and s["rows"] == 1
        probe = _probe(env, "ledger")
        assert probe["status"] == "ok"
        assert probe["data"]["signoffs"] == 1 and probe["data"]["signoffs_chain_ok"] is True

    def test_a_tampered_sign_off_is_reported_everywhere_and_licenses_nothing(
        self, env: Env
    ) -> None:
        clear_policy(env)
        assert _tier(env) == "automated-pass"
        created = env.post("/signoffs", json=attested_body(env, DELIVER_CELL)).json()
        assert created["active"] is True and created["chain_ok"] is True
        # not vacuous: the sign-off lifts the full cell before anything is altered
        assert _tier(env) == "human-verified"
        _drop_trigger(env.factory, "signoffs")
        with env.factory() as s:
            s.execute(
                text("UPDATE signoffs SET verifier = :v WHERE signoff_id = :id"),
                {"v": user_id("appr1"), "id": created["id"]},
            )
            s.commit()
        d = env.get("/ledger/verify").json()
        assert d["ok"] is False and d["signoffs"]["chain_ok"] is False
        assert d["signoffs"]["broken_at"] == 1 and "row_hash mismatch" in d["signoffs"]["detail"]
        v = env.get("/signoffs/verify").json()
        assert v["ok"] is False and v["broken_at"] == 1
        probe = _probe(env, "ledger")
        assert probe["status"] == "down" and "sign-off chain" in probe["detail"]
        assert env.get("/health").status_code == 503
        served = env.get(f"/signoffs/{created['id']}").json()
        assert served["active"] is False and served["tampered"] is True
        assert served["chain_ok"] is False
        # the full cell, the one the delivery gate reads, is no longer lifted
        assert _tier(env) == "automated-pass"

    def test_a_tampered_revocation_never_revives_the_licence_it_withdrew(self, env: Env) -> None:
        """The skeptic's variant: re-scoping a REVOCATION row un-revokes the attestation it
        withdrew. A per-row check reads the edited row as a revocation of the scope the
        attacker chose; a broken chain lifts nothing at all."""
        clear_policy(env)
        created = env.post("/signoffs", json=attested_body(env, DELIVER_CELL)).json()
        assert _tier(env) == "human-verified"
        r = env.post(f"/signoffs/{created['id']}/revoke", json={"note": "withdrawn"})
        assert r.status_code == 200, r.text
        assert _tier(env) == "automated-pass"
        with env.factory() as s, pytest.raises(IntegrityError, match="append-only"):
            s.execute(_REPLACE_REVOCATION)
        _drop_trigger(env.factory, "signoffs")
        with env.factory() as s:
            s.execute(_MOVE_REVOCATION)
            s.commit()
            moved = s.execute(select(Signoff).where(Signoff.revoke.is_(True))).scalar_one()
            assert moved.cell_json["size"] == "XL"
        # the revoked cell stays unlicensed on the delivery gate's projection
        assert _tier(env) == "automated-pass"
        served = env.get(f"/signoffs/{created['id']}").json()
        assert served["active"] is False and served["chain_ok"] is False
        listed = env.get(f"/signoffs?repo={ALPHA}&include_revoked=true").json()["items"]
        assert listed and not [i for i in listed if i["active"]]
        assert env.get("/signoffs/verify").json()["ok"] is False
        assert env.get("/health").status_code == 503

    def test_a_tampered_review_is_reported_by_the_ledger_verify_and_the_probe(
        self, env: Env
    ) -> None:
        login(env.client, "operator")
        row = accepted_row(env, DELIVER_CELL)
        r = env.post(
            "/reviews",
            json={
                "grade_row_hash": row.row_hash,
                "statement": "could not load it",
                "not_reviewed": True,
            },
        )
        assert r.status_code == 201, r.text
        _drop_trigger(env.factory, "reviews")
        with env.factory() as s:
            s.execute(text("UPDATE reviews SET statement = 'edited'"))
            s.commit()
        d = env.get("/ledger/verify").json()
        assert d["ok"] is False and d["reviews"]["chain_ok"] is False
        assert d["reviews"]["broken_at"] == 1
        probe = _probe(env, "ledger")
        assert probe["status"] == "down" and "review chain" in probe["detail"]


def test_the_grades_rows_are_untouched_by_every_check_here(env: Env) -> None:
    """Sanity: verifying reads; the seed's 50 rows stay 50."""
    env.get("/ledger/verify")
    env.get("/signoffs/verify")
    with env.factory() as s:
        assert len(list(s.execute(select(Grade.seq)).scalars())) == 50
