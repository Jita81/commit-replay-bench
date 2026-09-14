"""``/reviews``, ``/reviews/verify``, ``/reviews/stats`` and the retained-artefact routes
``/grades/{row_hash}/{retained,patch,transcript}``.

The patch route is exercised on a REAL retained worktree: a ``pyrepo`` trial with a
source edit and an untracked new file, whose :meth:`Workspace.diff_stats` hash is the
pack's ``diff_sha256`` — the served bytes must hash to exactly that (the drift guard
between the grader's hashing and the route's recomputation).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from crb.core.evidence import ApparatusStamp, BuilderRef, EvidencePack
from crb.core.grade import Belts, GradeResult
from crb.core.ledger import GradeRow, grade_row_from_result
from crb.server.routes.grades import (
    HDR_DIFF_SHA,
    HDR_PATCH_SHA,
    HDR_REDACTED,
    HDR_SERVED_SHA,
    HDR_TRUNCATED,
    HDR_VERIFIED,
    build_retained_patch,
    retained_patch_text,
    worktree_path,
)
from crb.store.ledger import DbLedger
from crb.store.models import Event, Run, Task
from fixtures import pyrepo as pr
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, login, make_env

RETAINED_RUN = "9" * 32
SECRET_LINE = 'API_KEY = "sk-live-abcdefghijklmnopqrstuvwxyz0123"\n'


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def count_over(patch: str, files: list[str]) -> tuple[int, int]:
    """``(+, −)`` over the hunks of ``files`` — the pack's counting rule."""
    adds = dels = 0
    current = ""
    for ln in patch.splitlines():
        if ln.startswith("+++ b/"):
            current = ln[6:]
        elif current not in files:
            continue
        elif ln.startswith("+") and not ln.startswith("+++"):
            adds += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            dels += 1
    return adds, dels


class Retained:
    """A graded row with a REAL retained worktree + transcript under the API's home."""

    def __init__(self, env: Env, tmp_path: Path, *, secret: bool = False, transcript: bool = True):
        self.env = env
        repo = pr.build(tmp_path / "pyrepo")
        task = repo.feat_task(repo=ALPHA)
        self.task = task
        with env.factory() as s:
            s.add(
                Task(
                    repo=ALPHA,
                    task_id=task.task_id,
                    pool=task.pool,
                    size=task.size,
                    capability_class=task.capability_class,
                    language=task.language,
                    authored=task.authored,
                    subject=task.subject,
                    red_checked=task.red_checked,
                    gold_clean=task.gold_clean,
                    spec_json=task.to_dict(),
                )
            )
            s.add(
                Run(
                    id=RETAINED_RUN,
                    repo=ALPHA,
                    kind="replay",
                    status="succeeded",
                    builder="editblock",
                    model="m",
                    provider="p",
                    ladder_json=["r1"],
                    params_json={"retain": {"worktrees": True, "transcripts": transcript}},
                    actor="op1",
                )
            )
            s.commit()
        # the worktree exactly where run_task leaves it
        root = worktree_path(
            Path(env.settings.home) / "scratch",
            repo=ALPHA,
            task_id=task.task_id,
            run_id=RETAINED_RUN,
            trial="r1",
        )
        self.ws = repo.trial(root)
        pr.apply_gold(self.ws)
        pr.write_files(self.ws, [("src/calc/extra.py", "def extra():\n    return 1\n")])
        if secret:
            pr.write_files(self.ws, [("src/calc/creds.py", SECRET_LINE)])
        diff = self.ws.diff_stats(exclude=task.test_files)
        self.diff_sha = diff.diff_sha256
        tref = ""
        if transcript:
            tdir = Path(env.settings.home) / "transcripts" / RETAINED_RUN
            tdir.mkdir(parents=True)
            tpath = tdir / f"{task.short_id}-editblock-deadbeef.json"
            tpath.write_text(json.dumps({"task_id": task.task_id, "outcome": {"transcript": []}}))
            tref = str(tpath)
        result = GradeResult(
            task_id=task.task_id,
            repo=ALPHA,
            mode="sighted",
            clean=True,
            belts=Belts(True, True, True, True, True),
            diff=diff,
            changed_files=list(diff.files),
        )
        builder = BuilderRef(name="editblock", model="m", provider="p", transcript_ref=tref)
        pack = EvidencePack(
            task=task,
            grade=result,
            apparatus=ApparatusStamp(runner="pytest", executor={"kind": "local"}),
            builder=builder,
            run_id=RETAINED_RUN,
            trial="r1",
            actor="worker-1",
            notes={"rung": "r1", "transcript_ref": tref} if tref else {"rung": "r1"},
        )
        ledger = DbLedger(env.factory)
        ledger.store_pack(pack)
        self.pack_hash = pack.pack_hash
        self.row: GradeRow = ledger.append(
            grade_row_from_result(
                result, task, pack_hash=pack.pack_hash, builder=builder, run_id=RETAINED_RUN
            )
        )

    def patch(self) -> Any:
        return self.env.get(f"/grades/{self.row.row_hash}/patch")

    def review_body(self, **over: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "grade_row_hash": self.row.row_hash,
            "statement": "read every hunk; the extra module is dead code",
            "findings": [],
            "patch_sha256": self.diff_sha,
        }
        body.update(over)
        return body


# ---------------------------------------------------------------------------
# retained patch
# ---------------------------------------------------------------------------


class TestRetainedPatch:
    def test_served_patch_hashes_to_the_packs_diff_sha256(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        # the route's recomputation == the grader's hashing, on a worktree with an
        # untracked new file (the case that carried an empty hash before 2026-09-14)
        assert hashlib.sha256(retained_patch_text(r.ws.root).encode()).hexdigest() == r.diff_sha
        res = r.patch()
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/x-diff")
        assert res.headers[HDR_DIFF_SHA] == r.diff_sha
        assert res.headers[HDR_PATCH_SHA] == r.diff_sha
        assert res.headers[HDR_VERIFIED] == "true"
        assert res.headers[HDR_REDACTED] == "false" and res.headers[HDR_TRUNCATED] == "false"
        served = hashlib.sha256(res.content).hexdigest()
        assert served == r.diff_sha == res.headers[HDR_SERVED_SHA]
        assert res.headers["cache-control"] == "no-store"
        body = res.text
        assert "diff --git a/src/calc/__init__.py" in body
        assert "+++ b/src/calc/extra.py" in body  # the untracked file is part of the patch
        assert "def subtract" in body
        # the pack's counts describe the same text over the files it lists (the
        # overlaid test file is in the hashed text but excluded from the counts)
        pack = env.get(f"/evidence/{r.pack_hash}").json()["pack"]
        adds, dels = count_over(body, pack["grade"]["diff"]["files"])
        assert (pack["grade"]["diff"]["additions"], pack["grade"]["diff"]["deletions"]) == (
            adds,
            dels,
        )
        assert "+++ b/tests/test_subtract.py" in body  # the oracle overlay IS in the hashed text

    def test_retained_status_says_what_is_reachable(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        st = env.get(f"/grades/{r.row.row_hash}/retained")
        assert st.status_code == 200
        body = st.json()
        assert body["patch_available"] is True and body["transcript_available"] is True
        assert body["retain_worktrees"] is True and body["retain_transcripts"] is True
        assert body["diff_sha256"] == r.diff_sha and body["run_id"] == RETAINED_RUN
        assert body["patch_reason"] == "" and body["transcript_reason"] == ""

    def test_redaction_changes_the_served_bytes_and_says_so(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path, secret=True)
        res = r.patch()
        assert res.status_code == 200
        assert "sk-live-" not in res.text and "[REDACTED" in res.text
        assert res.headers[HDR_REDACTED] == "true"
        # the worktree still hashes to the anchor; the SERVED bytes do not
        assert res.headers[HDR_VERIFIED] == "true" and res.headers[HDR_PATCH_SHA] == r.diff_sha
        assert hashlib.sha256(res.content).hexdigest() != r.diff_sha
        assert res.headers[HDR_SERVED_SHA] == hashlib.sha256(res.content).hexdigest()

    def test_cap_truncates_and_says_so(self, tmp_path: Path) -> None:
        repo = pr.build(tmp_path / "pyrepo")
        ws = repo.trial(tmp_path / "wt")
        pr.write_files(ws, [("src/calc/big.py", "x = 1\n" * 5000)])
        full = build_retained_patch(ws.root, "", cap=10_000_000)
        assert not full.truncated and not full.verified  # no anchor given → not verified
        capped = build_retained_patch(ws.root, full.patch_sha256, cap=1000)
        assert capped.truncated and capped.verified and len(capped.body.encode()) <= 1000
        assert capped.headers()[HDR_TRUNCATED] == "true"

    def test_a_drifted_worktree_is_served_unverified(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        (r.ws.root / "src/calc/extra.py").write_text("def extra():\n    return 2\n")
        res = r.patch()
        assert res.status_code == 200
        assert res.headers[HDR_VERIFIED] == "false"
        assert res.headers[HDR_PATCH_SHA] != r.diff_sha and res.headers[HDR_DIFF_SHA] == r.diff_sha

    def test_404_reasons(self, env: Env, tmp_path: Path) -> None:
        # unknown row
        res = env.get(f"/grades/{'0' * 64}/patch")
        assert res.status_code == 404 and envelope(res)["code"] == "not_found"
        # a seeded row: no diff in its pack, no retention on its run
        seeded = env.info.rows[0]
        res = env.get(f"/grades/{seeded.row_hash}/patch")
        assert res.status_code == 404
        e = envelope(res)
        assert e["code"] == "patch_unavailable" and "records no diff" in e["detail"]["reason"]
        assert e["detail"]["retain_worktrees"] is False
        res = env.get(f"/grades/{seeded.row_hash}/transcript")
        assert res.status_code == 404
        e = envelope(res)
        assert e["code"] == "transcript_unavailable"
        assert "not retained" in e["detail"]["reason"]
        # a retained row whose worktree was removed by retention
        r = Retained(env, tmp_path)
        r.ws.remove()
        res = r.patch()
        assert res.status_code == 404
        assert "no longer exists" in envelope(res)["detail"]["reason"]
        # a legacy (imported) row: no diff, no run
        legacy = next(row for row in env.info.rows if row.belt_set == "v3-legacy")
        res = env.get(f"/grades/{legacy.row_hash}/patch")
        assert res.status_code == 404 and envelope(res)["code"] == "patch_unavailable"

    def test_not_retained_worktree_reason(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        with env.factory() as s:
            run = s.get(Run, RETAINED_RUN)
            assert run is not None
            run.params_json = {}
            s.commit()
        r.ws.remove()
        res = r.patch()
        assert res.status_code == 404
        assert "did not retain worktrees" in envelope(res)["detail"]["reason"]

    def test_viewer_may_read_anonymous_may_not(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "viewer")
        assert r.patch().status_code == 200
        assert env.get(f"/grades/{r.row.row_hash}/transcript").status_code == 200
        env.client.cookies.clear()
        assert r.patch().status_code == 401


class TestRetainedTranscript:
    def test_served_from_inside_the_transcripts_dir_only(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        res = env.get(f"/grades/{r.row.row_hash}/transcript")
        assert res.status_code == 200 and res.headers["content-type"].startswith("application/json")
        assert res.json()["task_id"] == r.task.task_id
        # a pack whose reference points elsewhere is refused, never opened
        outside = tmp_path / "outside.json"
        outside.write_text("{}")
        with env.factory() as s:
            from crb.store.models import EvidencePackRow

            row = s.get(EvidencePackRow, r.pack_hash)
            assert row is not None
            body = dict(row.body_json)
            body["builder"] = {**body["builder"], "transcript_ref": str(outside)}
            s.execute(text("DROP TRIGGER evidence_no_update"))
            s.execute(
                text("UPDATE evidence SET body_json = :b WHERE pack_hash = :h"),
                {"b": json.dumps(body), "h": r.pack_hash},
            )
            s.commit()
        res = env.get(f"/grades/{r.row.row_hash}/transcript")
        assert res.status_code == 404
        assert "outside the transcripts directory" in envelope(res)["detail"]["reason"]

    def test_swept_transcript_404(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        for p in (Path(env.settings.home) / "transcripts").rglob("*.json"):
            p.unlink()
        res = env.get(f"/grades/{r.row.row_hash}/transcript")
        assert res.status_code == 404
        assert "no longer exists" in envelope(res)["detail"]["reason"]


# ---------------------------------------------------------------------------
# reviews
# ---------------------------------------------------------------------------


class TestReviews:
    def test_rbac(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        assert_rbac(env, "GET", "/reviews", min_role="viewer")
        assert_rbac(env, "GET", "/reviews/verify", min_role="viewer")
        assert_rbac(env, "GET", f"/reviews/stats?repo={ALPHA}", min_role="viewer")
        assert_rbac(env, "POST", "/reviews", min_role="operator", json=r.review_body())

    def test_csrf_is_required_on_the_write(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        token = env.client.headers.pop("X-CSRF-Token")
        res = env.post("/reviews", json=r.review_body())
        assert res.status_code == 403 and envelope(res)["code"] == "csrf_failed"
        env.client.headers["X-CSRF-Token"] = token
        assert env.post("/reviews", json=r.review_body()).status_code == 201

    def test_create_ok_review_then_a_defect_review(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        res = env.post("/reviews", json=r.review_body(mergeable=True))
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["verdict"] == "ok" and body["mergeable"] is True and body["findings"] == []
        assert body["grade_row_hash"] == r.row.row_hash and body["task_id"] == r.task.task_id
        assert body["patch_sha256_reviewed"] == r.diff_sha
        assert body["evidence_pack_hash"] == r.pack_hash and body["repo"] == ALPHA
        assert body["subject"] == "feat: add subtract" and body["grade_clean"] is True
        assert body["reviewer"] and body["schema"] == "crb.review.v1"
        assert body["prev_hash"] == "0" * 64 and len(body["row_hash"]) == 64
        assert body["apparatus_version"] == r.row.apparatus_version

        res = env.post(
            "/reviews",
            json=r.review_body(
                findings=[
                    {
                        "kind": "defect",
                        "note": "extra() is unreachable",
                        "file": "src/calc/extra.py",
                        "line": 1,
                    },
                    {"kind": "style", "note": "no docstring"},
                ],
                mergeable=False,
                statement="two findings",
            ),
        )
        assert res.status_code == 201, res.text
        second = res.json()
        assert second["verdict"] == "defect" and second["prev_hash"] == body["row_hash"]
        assert [f["kind"] for f in second["findings"]] == ["defect", "style"]
        assert second["findings"][0]["line"] == 1

        # list, filters, get
        page = env.get(f"/reviews?grade_row_hash={r.row.row_hash}").json()
        assert page["total"] == 2 and [i["verdict"] for i in page["items"]] == ["ok", "defect"]
        assert env.get(f"/reviews?repo={ALPHA}&verdict=defect").json()["total"] == 1
        assert env.get(f"/reviews?task_id={r.task.task_id}").json()["total"] == 2
        assert env.get("/reviews?repo=beta").json()["total"] == 0
        one = env.get(f"/reviews/{second['review_id']}")
        assert one.status_code == 200 and one.json()["row_hash"] == second["row_hash"]
        assert env.get("/reviews/nope").status_code == 404

        # every write is a system event, committed with it
        with env.factory() as s:
            actions = [
                e.action
                for e in s.execute(select(Event).where(Event.stage == "system")).scalars()
                if e.action.startswith("review.")
            ]
        assert actions == ["review.created", "review.created"]

        # verify: chain intact, every verdict anchored
        v = env.get("/reviews/verify").json()
        assert v == {
            **v,
            "rows": 2,
            "ok": True,
            "chain_ok": True,
            "broken_at": None,
            "anchored": 2,
            "unanchored": 0,
        }

    def test_client_verdict_must_agree(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        res = env.post("/reviews", json=r.review_body(verdict="defect"))
        assert res.status_code == 422
        e = envelope(res)
        assert e["code"] == "validation_error" and "contradicts" in e["message"]
        assert env.post("/reviews", json=r.review_body(verdict="ok")).status_code == 201

    def test_patch_hash_mismatch_is_422_review_refused(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        res = env.post("/reviews", json=r.review_body(patch_sha256="e" * 64))
        assert res.status_code == 422
        e = envelope(res)
        assert e["code"] == "review_refused" and e["detail"]["code"] == "patch_hash_mismatch"
        assert e["detail"]["expected"] == r.diff_sha and e["detail"]["observed"] == "e" * 64
        assert env.get("/reviews").json()["total"] == 0
        with env.factory() as s:  # the refusal is recorded, the review is not
            refused = [
                e
                for e in s.execute(select(Event).where(Event.stage == "system")).scalars()
                if e.action == "review.refused"
            ]
        assert len(refused) == 1 and refused[0].payload_json["code"] == "patch_hash_mismatch"
        # a missing hash is refused too — a verdict attests to bytes
        res = env.post("/reviews", json=r.review_body(patch_sha256=""))
        assert res.status_code == 422 and envelope(res)["detail"]["code"] == "patch_hash_missing"
        # and the served patch's hash is exactly what the server accepts
        served = hashlib.sha256(r.patch().content).hexdigest()
        assert env.post("/reviews", json=r.review_body(patch_sha256=served)).status_code == 201

    def test_a_row_whose_pack_has_no_diff_cannot_be_reviewed_but_can_be_not_reviewed(
        self, env: Env
    ) -> None:
        login(env.client, "operator")
        seeded = env.info.rows[0]
        body = {
            "grade_row_hash": seeded.row_hash,
            "statement": "nothing to read",
            "patch_sha256": "d" * 64,
        }
        res = env.post("/reviews", json=body)
        assert res.status_code == 422 and envelope(res)["detail"]["code"] == "no_diff_in_pack"
        res = env.post("/reviews", json={**body, "patch_sha256": "", "not_reviewed": True})
        assert res.status_code == 201, res.text
        assert res.json()["verdict"] == "not_reviewed" and res.json()["patch_sha256_reviewed"] == ""
        res = env.post(
            "/reviews", json={**body, "patch_sha256": "", "not_reviewed": True, "mergeable": True}
        )
        assert res.status_code == 422 and envelope(res)["code"] == "validation_error"

    def test_regression_is_never_mergeable(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        res = env.post(
            "/reviews",
            json=r.review_body(
                findings=[{"kind": "regression", "note": "breaks add"}], mergeable=True
            ),
        )
        assert res.status_code == 422 and "cannot be mergeable" in envelope(res)["message"]

    def test_unknown_row_and_malformed_bodies(self, env: Env) -> None:
        login(env.client, "operator")
        res = env.post(
            "/reviews",
            json={"grade_row_hash": "0" * 64, "statement": "x", "patch_sha256": "d" * 64},
        )
        assert res.status_code == 404
        res = env.post("/reviews", json={"grade_row_hash": "zz", "statement": "x"})
        assert res.status_code == 422
        res = env.post(
            "/reviews",
            json={
                "grade_row_hash": "0" * 64,
                "statement": "x",
                "findings": [{"kind": "ok", "note": "n"}],
            },
        )
        assert res.status_code == 422
        res = env.post("/reviews", json={"grade_row_hash": "0" * 64, "statement": "x", "bogus": 1})
        assert res.status_code == 422

    def test_statement_and_findings_are_redacted(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        res = env.post(
            "/reviews",
            json=r.review_body(
                statement="fixture has password=hunter2xyz in it",
                findings=[
                    {"kind": "style", "note": "token ghp_abcdefghijklmnopqrstuvwxyz0123 committed"}
                ],
            ),
        )
        assert res.status_code == 201
        body = res.json()
        assert "hunter2xyz" not in body["statement"] and "ghp_" not in body["findings"][0]["note"]

    def test_verify_reports_tamper_and_lost_anchor(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        first = env.post("/reviews", json=r.review_body()).json()
        env.post("/reviews", json=r.review_body(statement="again"))
        with env.factory() as s:
            s.execute(text("DROP TRIGGER IF EXISTS reviews_no_update"))
            s.execute(
                text("UPDATE reviews SET statement = 'edited' WHERE review_id = :id"),
                {"id": first["review_id"]},
            )
            s.commit()
        v = env.get("/reviews/verify").json()
        assert v["ok"] is False and v["chain_ok"] is False and v["broken_at"] == 1
        assert "row_hash mismatch" in v["detail"]
        # the audit surface still lists the edited row, column by column
        assert env.get("/reviews").json()["items"][0]["statement"] == "edited"
        # a review whose pack no longer carries the hash it attested to is unanchored
        with env.factory() as s:
            s.execute(text("DROP TRIGGER IF EXISTS reviews_no_update"))
            s.execute(
                text("UPDATE reviews SET patch_sha256_reviewed = :h WHERE review_id = :id"),
                {"h": "f" * 64, "id": first["review_id"]},
            )
            s.commit()
        v = env.get("/reviews/verify").json()
        assert v["anchored"] == 1 and v["unanchored"] == 1

    def test_stats_join_the_standing_verdict_onto_the_cells(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        full = "class,size,language,builder,model,provider,step"
        before = env.get(f"/reviews/stats?repo={ALPHA}&by={full}").json()
        assert before["n_reviews"] == 0 and all(c["n_reviewed"] == 0 for c in before["cells"])
        cell = next(c for c in before["cells"] if c["model"] == "m" and c["builder"] == "editblock")
        assert cell["n_rows"] == 1 and cell["capability_class"] == r.task.capability_class

        env.post("/reviews", json=r.review_body())
        env.post(
            "/reviews",
            json=r.review_body(findings=[{"kind": "defect", "note": "d"}], mergeable=False),
        )
        after = env.get(f"/reviews/stats?repo={ALPHA}&by={full}").json()
        assert after["n_reviews"] == 2
        cell = next(c for c in after["cells"] if c["model"] == "m" and c["builder"] == "editblock")
        # one row, reviewed twice: the standing verdict is the latest (defect)
        assert cell["n_reviewed"] == 1 and cell["n_review_defects"] == 1 and cell["n_defect"] == 1
        assert cell["n_ok"] == 0 and cell["n_not_mergeable"] == 1 and cell["reviewed_share"] == 1.0
        # projection follows the capability map's `by` (default class × size)
        default = env.get(f"/reviews/stats?repo={ALPHA}").json()
        assert default["by"] == ["capability_class", "size"]
        assert all(c["model"] == "*" for c in default["cells"])
        assert sum(c["n_reviewed"] for c in default["cells"]) == 1
        by_class = env.get(f"/reviews/stats?repo={ALPHA}&by=class").json()
        assert by_class["by"] == ["capability_class"]
        assert all(c["size"] == "*" for c in by_class["cells"])
        assert sum(c["n_reviewed"] for c in by_class["cells"]) == 1
        assert env.get("/reviews/stats?repo=nope").status_code == 404
        assert env.get(f"/reviews/stats?repo={ALPHA}&by=bogus").status_code == 422
        assert env.get("/reviews/stats?repo=beta").json()["cells"] == []

    def test_stats_refuse_a_false_q1_repo(self, env: Env) -> None:
        with env.factory() as s:
            s.execute(text("DROP TRIGGER grades_no_update"))
            s.execute(text("UPDATE grades SET target_green = 0 WHERE seq = 1"))
            s.commit()
        res = env.get(f"/reviews/stats?repo={ALPHA}")
        assert res.status_code == 409 and envelope(res)["code"] == "false_q1_refused"

    def test_reviews_table_is_append_only_through_the_store(self, env: Env, tmp_path: Path) -> None:
        r = Retained(env, tmp_path)
        login(env.client, "operator")
        env.post("/reviews", json=r.review_body())
        with env.factory() as s, pytest.raises(Exception, match="append-only"):
            s.execute(text("DELETE FROM reviews"))
            s.commit()
