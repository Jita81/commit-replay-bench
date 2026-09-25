"""``/ledger/*`` — verify (reports, never raises), export (verifies standalone), abstract, import.

Navigation
----------
What it is:   ``/ledger/*``'s test suite — verify (reports, never raises), export (verifies
              standalone), abstract, import.
What it does: Pins that verify reports ok, ``broken_at`` on a tampered row and a broken link on a
              deleted one, counts false-Q1 over the STORED belts, a viewer reads; that the JSONL
              export verifies standalone, the default format and repo filter, CSV with a header
              and formula cells neutralised, 422 on a bad format, the abstract export is
              operator-only and allowlisted, anonymous 401; and that import is admin-only,
              re-chains and skips duplicates, keeps belt 5 unrecorded on pre-belt-5 rows
              (ADR-0011), points census rows at the CLI, refuses a false-Q1 row with 409 and
              malformed bodies with 422.
How:          ``make_env`` over the seed; triggers dropped deliberately for the tamper cases.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0007-abstract-cell-export-only.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/server/routes/ledger.py (under test), src/crb/store/ledger.py (verify,
              import, export), src/crb/core/federated.py (the abstract allowlist),
              tests/fixtures/server_seed.py, docs/API.md (ledger)
Tested by:    tests/test_server_routes_ledger.py
Touch when:   an export format is added (a header / escaping case); a row field is added (the
              CSV and abstract cases decide whether it is exported).
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from crb.core.federated import ABSTRACT_ALLOWLIST
from crb.core.ledger import GENESIS_HASH, GradeRow, verify_chain
from crb.server.app import API_PREFIX
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, login, make_env


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as admin, torn down after the test."""
    with make_env(tmp_path) as e:
        yield e


def _drop_triggers(env: Env) -> None:
    with env.factory() as s:
        s.execute(text("DROP TRIGGER grades_no_update"))
        s.execute(text("DROP TRIGGER grades_no_delete"))
        s.commit()


class TestVerify:
    def test_ok(self, env: Env) -> None:
        r = env.get("/ledger/verify")
        assert r.status_code == 200
        d = r.json()
        assert set(d) == {
            "rows",
            "ok",
            "false_q1_total",
            "chain_ok",
            "broken_at",
            "detail",
            "clean_without_pack",
            "verified_at",
        }
        assert d["rows"] == 50 and d["ok"] is True and d["false_q1_total"] == 0
        assert d["chain_ok"] is True and d["broken_at"] is None and d["clean_without_pack"] == 0
        assert d["detail"] == "50 rows, chain intact, false_q1=0"

    def test_tampered_row_reports_broken_at(self, env: Env) -> None:
        _drop_triggers(env)
        with env.factory() as s:
            s.execute(text("UPDATE grades SET actor = 'mallory' WHERE seq = 7"))
            s.commit()
        d = env.get("/ledger/verify").json()
        assert d["ok"] is False and d["chain_ok"] is False and d["broken_at"] == 7
        assert "row_hash mismatch" in d["detail"] and d["rows"] == 50
        assert d["false_q1_total"] == 0

    def test_deleted_row_breaks_the_link(self, env: Env) -> None:
        _drop_triggers(env)
        with env.factory() as s:
            s.execute(text("DELETE FROM grades WHERE seq = 3"))
            s.commit()
        d = env.get("/ledger/verify").json()
        assert d["rows"] == 49 and d["broken_at"] == 4 and "prev_hash mismatch" in d["detail"]

    def test_false_q1_counted_over_stored_belts(self, env: Env) -> None:
        _drop_triggers(env)
        with env.factory() as s:
            # a legacy row: only three belts are recorded; flipping one is a false-Q1 too
            s.execute(
                text(
                    "UPDATE grades SET no_new_failures = 0 WHERE belt_set = 'v3-legacy' AND clean = 1 AND seq = (SELECT MIN(seq) FROM grades WHERE belt_set = 'v3-legacy' AND clean = 1)"
                )
            )
            s.execute(text("UPDATE grades SET evidence_pack_hash = '' WHERE seq = 1"))
            s.commit()
        d = env.get("/ledger/verify").json()
        assert d["false_q1_total"] == 1 and d["clean_without_pack"] == 1 and d["ok"] is False
        assert d["chain_ok"] is False  # the edits also broke the hashes — reported, not raised

    def test_viewer_reads(self, env: Env) -> None:
        login(env.client, "viewer")
        assert env.get("/ledger/verify").status_code == 200


class TestExport:
    def test_jsonl_verifies_standalone(self, env: Env) -> None:
        r = env.get("/ledger/export?format=jsonl")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        assert r.headers["content-disposition"] == 'attachment; filename="crb-ledger.jsonl"'
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        assert len(lines) == 50
        rows = [GradeRow.from_dict(json.loads(ln)) for ln in lines]
        assert verify_chain(rows) == 50
        assert set(json.loads(lines[0])) == set(GradeRow.__dataclass_fields__)
        assert "seq" not in json.loads(lines[0])

    def test_jsonl_default_format_and_repo_filter(self, env: Env) -> None:
        r = env.get(f"/ledger/export?repo={ALPHA}")
        assert r.status_code == 200 and r.headers["content-disposition"].endswith(
            '"crb-ledger-alpha.jsonl"'
        )
        rows = [GradeRow.from_dict(json.loads(ln)) for ln in r.text.splitlines() if ln.strip()]
        assert len(rows) == 50 and all(x.verify_hash() for x in rows)
        assert env.get("/ledger/export?repo=beta").text == ""

    def test_csv_has_header(self, env: Env) -> None:
        r = env.get("/ledger/export?format=csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert r.headers["content-disposition"] == 'attachment; filename="crb-ledger.csv"'
        reader = csv.reader(io.StringIO(r.text))
        header = next(reader)
        assert header == list(GradeRow.__dataclass_fields__)
        body = list(reader)
        assert len(body) == 50
        first = dict(zip(header, body[0], strict=True))
        assert first["clean"] == "true" and first["source_changed"] == "true"
        assert json.loads(first["labels"])["rung"] == "r1"
        legacy = [
            dict(zip(header, b, strict=True))
            for b in body
            if b[header.index("belt_set")] == "v3-legacy"
        ]
        assert legacy and legacy[0]["source_changed"] == ""  # null belt stays empty, never invented

    def test_csv_neutralises_formula_cells(self, env: Env) -> None:
        _drop_triggers(env)
        with env.factory() as s:
            s.execute(text("UPDATE grades SET error = '=HYPERLINK(\"http://x\")' WHERE seq = 2"))
            s.commit()
        r = env.get("/ledger/export?format=csv")
        header, *body = list(csv.reader(io.StringIO(r.text)))
        row = dict(zip(header, body[1], strict=True))
        assert row["error"].startswith("'=HYPERLINK")
        assert row["cost_usd"] == "0.012"  # numbers are untouched

    def test_bad_format_422(self, env: Env) -> None:
        r = env.get("/ledger/export?format=xml")
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"

    def test_abstract_is_operator_and_allowlisted(self, env: Env) -> None:
        assert_rbac(env, "GET", "/ledger/export/abstract", min_role="operator")
        login(env.client, "operator")
        r = env.get("/ledger/export/abstract")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
        cells = [json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
        assert len(cells) == 3
        for c in cells:
            assert set(c) == set(ABSTRACT_ALLOWLIST)  # no repo, no task ids, no timestamps
        deliver = next(c for c in cells if c["capability_class"] == "bug.fix")
        assert deliver["n"] == 40 and deliver["clean"] == 38 and deliver["false_q1"] == 0
        assert ALPHA not in r.text and "deadbeef" not in r.text

    def test_anonymous_401(self, env: Env) -> None:
        env.client.cookies.clear()
        assert env.client.get(f"{API_PREFIX}/ledger/export").status_code == 401


def _jsonl(rows: list[GradeRow]) -> bytes:
    return "".join(json.dumps(r.to_dict(), sort_keys=True) + "\n" for r in rows).encode()


class TestImport:
    def test_rbac_admin(self, env: Env) -> None:
        ladder = ["viewer", "operator", "approver"]
        for role in ladder:
            login(env.client, role)
            r = env.client.post(
                f"{API_PREFIX}/ledger/import",
                files={"file": ("x.jsonl", b"", "application/x-ndjson")},
            )
            assert r.status_code == 403, role
        env.client.cookies.clear()
        env.client.headers.pop("X-CSRF-Token", None)
        r = env.client.post(f"{API_PREFIX}/ledger/import", files={"file": ("x.jsonl", b"")})
        assert r.status_code == 401

    def test_import_rechains_and_skips_duplicates(self, env: Env) -> None:
        # a foreign ledger: the same five verdicts recorded for repo "gamma", chained on their own
        prev = GENESIS_HASH
        foreign: list[GradeRow] = []
        for src in env.info.rows[:5]:
            d = src.to_dict()
            d.update(repo="gamma", row_id=f"foreign-{len(foreign)}", prev_hash="", row_hash="")
            d["evidence_pack_hash"] = "f" * 64  # a pack this ledger has never seen
            row = GradeRow.from_dict(d).chained(prev)
            foreign.append(row)
            prev = row.row_hash
        assert verify_chain(foreign) == 5
        r = env.client.post(
            f"{API_PREFIX}/ledger/import",
            files={"file": ("foreign.jsonl", _jsonl(foreign), "application/x-ndjson")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d == {"read": 5, "imported": 5, "skipped": 0, "rows": 55, "source_chain_ok": True}
        assert env.get("/ledger/verify").json()["ok"] is True  # re-chained onto THIS ledger
        page = env.get("/grades?repo=gamma").json()
        assert page["total"] == 5
        first = page["items"][0]
        assert first["labels"]["source_row_hash"] == foreign[0].row_hash
        assert first["prev_hash"] == env.info.rows[-1].row_hash and first["row_id"] == "foreign-0"
        # importing the same file again skips everything (row_id / pack hash already present)
        r = env.client.post(
            f"{API_PREFIX}/ledger/import",
            files={"file": ("foreign.jsonl", _jsonl(foreign), "application/x-ndjson")},
        )
        assert r.json() == {
            "read": 5,
            "imported": 0,
            "skipped": 5,
            "rows": 55,
            "source_chain_ok": True,
        }
        # a file whose own chain is broken is still imported (re-chained), but says so
        broken = list(foreign)
        broken[2] = GradeRow.from_dict(
            {**broken[2].to_dict(), "row_id": "foreign-x", "evidence_pack_hash": "e" * 64}
        )
        r = env.client.post(
            f"{API_PREFIX}/ledger/import", files={"file": ("broken.jsonl", _jsonl(broken))}
        )
        assert r.status_code == 200 and r.json()["source_chain_ok"] is False
        assert r.json()["imported"] == 1 and r.json()["skipped"] == 4

    def test_pre_belt_five_rows_verify_in_the_store_with_belt_five_unrecorded(
        self, env: Env
    ) -> None:
        """ADR-0011: a ``v4`` row (four belts, ``repo_lint_clean`` unrecorded) and a ``v5``
        row (belt 5 recorded, here rejected) imported side by side — the store's own
        verify recomputes each hash by the SAME body rule the core uses, so the chain is
        intact and the v5 rejection is a plain non-clean row, never a false-Q1."""
        src = env.info.rows[0].to_dict()
        v4 = GradeRow.from_dict(
            {
                **src,
                "repo": "delta",
                "row_id": "delta-v4",
                "belt_set": "v4",
                "apparatus_version": "2.1",  # the pre-belt-5 apparatus that wrote v4 rows
                "repo_lint_clean": None,
                "evidence_pack_hash": "a" * 64,
                "prev_hash": "",
                "row_hash": "",
            }
        ).chained(GENESIS_HASH)
        v5 = GradeRow.from_dict(
            {
                **src,
                "repo": "delta",
                "row_id": "delta-v5",
                "clean": False,
                "apparatus_version": "2.2",  # the first belt-5 apparatus (no posture yet)
                "belt_set": "v5",
                "repo_lint_clean": False,
                "evidence_pack_hash": "b" * 64,
                "labels": {},
                "prev_hash": "",
                "row_hash": "",
            }
        ).chained(v4.row_hash)
        assert "repo_lint_clean" not in v4.body() and v5.body()["repo_lint_clean"] is False
        r = env.client.post(
            f"{API_PREFIX}/ledger/import",
            files={"file": ("delta.jsonl", _jsonl([v4, v5]), "application/x-ndjson")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 2 and r.json()["source_chain_ok"] is True
        verify = env.get("/ledger/verify").json()
        assert verify["ok"] is True and verify["chain_ok"] is True and verify["false_q1_total"] == 0
        items = {g["row_id"]: g for g in env.get("/grades?repo=delta").json()["items"]}
        assert (
            items["delta-v4"]["belt_set"] == "v4" and items["delta-v4"]["repo_lint_clean"] is None
        )
        assert items["delta-v5"]["repo_lint_clean"] is False and items["delta-v5"]["clean"] is False
        assert GradeRow.from_dict(items["delta-v5"]).failure_kind == "lint"

    def test_census_rows_point_at_the_cli(self, env: Env) -> None:
        census = {
            "repo": "sqlalchemy",
            "task": "abc1234",
            "clean": True,
            "wave": "w1",
            "tests_unmodified": True,
        }
        r = env.client.post(
            f"{API_PREFIX}/ledger/import",
            files={"file": ("grades.jsonl", (json.dumps(census) + "\n").encode())},
        )
        assert r.status_code == 422
        e = envelope(r)
        assert e["code"] == "census_import_unsupported" and e["detail"]["line"] == 1
        assert e["detail"]["use"].startswith("crb ledger import-census")

    def test_false_q1_row_refused_409(self, env: Env) -> None:
        bad = env.info.rows[0].to_dict()
        bad["target_green"] = False  # clean stays True
        r = env.client.post(
            f"{API_PREFIX}/ledger/import",
            files={"file": ("bad.jsonl", (json.dumps(bad) + "\n").encode())},
        )
        assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"
        assert envelope(r)["detail"] == {"line": 1}
        assert env.get("/ledger/verify").json()["rows"] == 50

    def test_malformed_422(self, env: Env) -> None:
        r = env.client.post(
            f"{API_PREFIX}/ledger/import", files={"file": ("x.jsonl", b"not json\n")}
        )
        assert r.status_code == 422 and envelope(r)["detail"] == {"line": 1}
        r = env.client.post(f"{API_PREFIX}/ledger/import", files={"file": ("x.jsonl", b"[1,2]\n")})
        assert r.status_code == 422
        r = env.client.post(
            f"{API_PREFIX}/ledger/import",
            files={"file": ("x.jsonl", b'{"schema": "crb.grade.v2", "repo": "a"}\n')},
        )
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"
        r = env.client.post(f"{API_PREFIX}/ledger/import", files={"file": ("x.jsonl", b"\xff\xfe")})
        assert r.status_code == 422
        r = env.client.post(f"{API_PREFIX}/ledger/import", files={"file": ("x.jsonl", b"\n\n")})
        assert r.status_code == 200 and r.json() == {
            "imported": 0,
            "skipped": 0,
            "read": 0,
            "rows": 50,
            "source_chain_ok": None,
        }
