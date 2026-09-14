"""crb.core.signoff — human attestations: append-only, hash-chained, revocable, and
NEVER able to lift a false-Q1 cell (refused at write, re-checked at read).

Ports the upstream test_signoff_ledger cases onto crb types and adds the chain,
the write-boundary refusal (→ HTTP 409 at the API) and the scope rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core import capability as cap
from crb.core import signoff as so
from crb.core.ledger import GradeRow, LedgerIntegrityError
from crb.core.routing import ROUTE_DELIVER
from crb.core.version import APPARATUS_VERSION

PACK = "b" * 64


def _row(
    *,
    clean: bool = True,
    cls: str = "frontend.component.add",
    size: str = "S",
    language: str = "python",
    model: str = "gpt-oss-120b",
    repo: str = "todo",
    task_id: str = "0123456789abcdef",
) -> GradeRow:
    return GradeRow(
        repo=repo,
        task_id=task_id,
        clean=clean,
        tests_unmodified=True,
        target_green=clean,
        no_new_failures=True,
        source_changed=True,
        capability_class=cls,
        size=size,
        language=language,
        builder="cline",
        model=model,
        provider="cerebras",
        evidence_pack_hash=PACK if clean else "",
    )


def _rows(n: int, clean: int, **kw: object) -> list[GradeRow]:
    return [_row(clean=i < clean, task_id=f"{i:016x}", **kw) for i in range(n)]  # type: ignore[arg-type]


def _cell(rows: list[GradeRow], **key: str) -> cap.CapabilityCell:
    return cap.build_capability_map(rows).get(**key)


def _signoff(
    cls: str = "frontend.component.add",
    *,
    repo: str = "todo",
    size: str = "*",
    verifier: str = "alice@x.com",
    revoked: bool = False,
    tier: str = cap.TIER_HUMAN_VERIFIED,
    note: str = "reviewed evidence",
    **scope: str,
) -> so.SignoffRecord:
    return so.SignoffRecord(
        repo=repo,
        capability_class=cls,
        size=size,
        verifier=verifier,
        verified_at="2026-06-05T01:00:00+00:00",
        note=note,
        revoked=revoked,
        tier=tier,
        **scope,
    )


# ---------------------------------------------------------------------------
# record invariants
# ---------------------------------------------------------------------------


def test_record_requires_class_verifier_and_earned_tier() -> None:
    with pytest.raises(ValueError, match="capability_class"):
        _signoff("*")
    with pytest.raises(ValueError, match="verifier"):
        _signoff(verifier="")
    with pytest.raises(ValueError, match="tier must be"):
        _signoff(tier=cap.TIER_AUTOMATED_PASS)
    with pytest.raises(ValueError, match="repo is required"):
        _signoff(repo="")


def test_record_refuses_false_q1_snapshot_and_redacts_note() -> None:
    with pytest.raises(so.SignoffRefused):
        so.SignoffRecord(repo="todo", capability_class="c", verifier="v", false_q1_at_signoff=1)
    rec = _signoff(note="token=sk-live-abcdefghijklmnopqrstuvwxyz0123")
    assert "sk-live" not in rec.note and "REDACTED" in rec.note


def test_record_roundtrip_and_hash() -> None:
    rec = _signoff().chained("0" * 64)
    assert rec.verify_hash()
    again = so.SignoffRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert again == rec and again.verify_hash()
    assert rec.key() == ("todo", "*", "frontend.component.add", "*", "*", "*", "*", "*")


# ---------------------------------------------------------------------------
# ledger: append / load / chain / revoke (upstream cases)
# ---------------------------------------------------------------------------


def test_append_load_roundtrip(tmp_path: Path) -> None:
    rows = _rows(12, 12)
    cell = _cell(rows, capability_class="frontend.component.add", size="S")
    p = tmp_path / "signoff.jsonl"
    led = so.JsonlSignoffLedger(p)
    a = led.append(_signoff(repo="todo"), cell, repo="todo")
    b = led.append(_signoff(repo="cart"), cell, repo="cart")
    loaded = list(led.records())
    assert [r.repo for r in loaded] == ["todo", "cart"]
    assert loaded[0].verifier == "alice@x.com"
    # evidence snapshot stamped from the live cell
    assert a.n_at_signoff == 12 and a.point_at_signoff == 1.0 and a.false_q1_at_signoff == 0
    assert a.apparatus_version == APPARATUS_VERSION  # stamped from the instrument, never a literal
    # chained
    assert a.prev_hash == "0" * 64 and b.prev_hash == a.row_hash
    assert led.verify() == 2


def test_chain_detects_tamper(tmp_path: Path) -> None:
    rows = _rows(12, 12)
    cell = _cell(rows, capability_class="frontend.component.add", size="S")
    p = tmp_path / "signoff.jsonl"
    led = so.JsonlSignoffLedger(p)
    led.append(_signoff(), cell, repo="todo")
    led.append(_signoff(verifier="bob@x.com"), cell, repo="todo")
    lines = p.read_text().splitlines()
    d = json.loads(lines[0])
    d["verifier"] = "mallory@x.com"
    lines[0] = json.dumps(d, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(LedgerIntegrityError, match="row_hash mismatch"):
        led.verify()
    # removing a record breaks the chain too
    p.write_text(lines[1] + "\n")
    with pytest.raises(LedgerIntegrityError, match="prev_hash mismatch"):
        led.verify()


def test_active_signoffs_latest_wins_and_revoke_drops(tmp_path: Path) -> None:
    rows = _rows(12, 12)
    cell = _cell(rows, capability_class="frontend.component.add", size="S")
    led = so.JsonlSignoffLedger(tmp_path / "signoff.jsonl")
    led.append(_signoff(verifier="alice@x.com"), cell, repo="todo")
    led.append(_signoff(verifier="bob@x.com"), cell, repo="todo")  # newer attestation
    active = so.active_signoffs(led.records())
    key = _signoff().key()
    assert active[key].verifier == "bob@x.com"
    led.append(_signoff(verifier="bob@x.com", revoked=True))  # revocation needs no cell
    assert key not in so.active_signoffs(led.records())
    assert led.verify() == 3


# ---------------------------------------------------------------------------
# write boundary: refusals (→ 409)
# ---------------------------------------------------------------------------


def test_write_refuses_false_q1_cell(tmp_path: Path) -> None:
    bad = _row()
    object.__setattr__(bad, "target_green", False)  # a false-Q1 row that bypassed write
    cell = _cell([*_rows(12, 12), bad], capability_class="frontend.component.add", size="S")
    assert cell.false_q1 == 1
    led = so.JsonlSignoffLedger(tmp_path / "s.jsonl")
    with pytest.raises(so.SignoffRefused, match="false_q1=1"):
        led.append(_signoff(), cell, repo="todo")
    assert not (tmp_path / "s.jsonl").exists()  # nothing written


def test_write_refuses_unmeasured_cell_and_missing_cell(tmp_path: Path) -> None:
    empty = _cell([], capability_class="frontend.component.add", size="S")
    led = so.JsonlSignoffLedger(tmp_path / "s.jsonl")
    with pytest.raises(so.SignoffRefused, match="no measured evidence"):
        led.append(_signoff(), empty, repo="todo")
    with pytest.raises(so.SignoffRefused, match="needs the live cell"):
        led.append(_signoff())


def test_write_refuses_scope_mismatch(tmp_path: Path) -> None:
    cell = _cell(_rows(12, 12), capability_class="frontend.component.add", size="S")
    led = so.JsonlSignoffLedger(tmp_path / "s.jsonl")
    with pytest.raises(so.SignoffRefused, match="does not cover"):
        led.append(_signoff("bug.fix"), cell, repo="todo")
    with pytest.raises(so.SignoffRefused, match="does not cover"):
        led.append(_signoff(repo="todo"), cell, repo="cart")  # attested for another repo
    # a language-scoped record does not cover a class-wide (language="*") cell
    with pytest.raises(so.SignoffRefused, match="does not cover"):
        led.append(_signoff(language="python"), cell, repo="todo")


# ---------------------------------------------------------------------------
# read overlay
# ---------------------------------------------------------------------------


def test_apply_signoffs_elevates_matching_cell_only() -> None:
    rows = _rows(12, 12, repo="todo") + _rows(12, 12, cls="bug.fix", repo="cart")
    m = cap.build_capability_map(rows)
    out = so.apply_signoffs_to_map(m, [_signoff()], repo="todo")
    assert (
        out.get(capability_class="frontend.component.add", size="S").verification_tier
        == "human-verified"
    )
    assert out.get(capability_class="frontend.component.add", size="S").earned
    assert out.get(capability_class="bug.fix", size="S").verification_tier == "automated-pass"
    # the original map is untouched (new cells)
    assert (
        m.get(capability_class="frontend.component.add", size="S").verification_tier
        == "automated-pass"
    )


def test_invariant_false_q1_can_never_be_signed_off_at_read() -> None:
    # An attestation exists (say, written before the dirty row appeared). New evidence
    # with false-Q1 arrives → the overlay refuses to lift; the gate self-heals.
    bad = _row()
    object.__setattr__(bad, "target_green", False)
    m = cap.build_capability_map([*_rows(12, 12), bad])
    out = so.apply_signoffs(m.cells, [_signoff()], repo="todo")
    assert out[0].verification_tier == cap.TIER_UNTRUSTED


def test_revoked_signoff_does_not_elevate() -> None:
    m = cap.build_capability_map(_rows(12, 12))
    out = so.apply_signoffs(m.cells, [_signoff(), _signoff(revoked=True)], repo="todo")
    assert out[0].verification_tier == "automated-pass"


def test_unscoped_read_applies_only_repo_agnostic_records() -> None:
    m = cap.build_capability_map(_rows(12, 12))
    # attested for "todo" only → an unscoped read must not borrow it
    assert (
        so.apply_signoffs(m.cells, [_signoff(repo="todo")])[0].verification_tier == "automated-pass"
    )
    # a "*" attestation applies everywhere
    assert so.apply_signoffs(m.cells, [_signoff(repo="*")], repo="anything")[0].earned


def test_highest_matching_tier_wins_and_never_downgrades() -> None:
    m = cap.build_capability_map(_rows(12, 12))
    recs = [_signoff(verifier="a"), _signoff(verifier="b", tier=cap.TIER_AB_CONFIRMED, size="S")]
    out = so.apply_signoffs(m.cells, recs, repo="todo")
    assert out[0].verification_tier == cap.TIER_AB_CONFIRMED
    # applying a lower tier on top does not downgrade
    out2 = so.apply_signoffs(out, [_signoff(verifier="c")], repo="todo")
    assert out2[0].verification_tier == cap.TIER_AB_CONFIRMED


def test_class_wide_attestation_covers_every_size_but_not_vice_versa() -> None:
    rows = _rows(12, 12, size="S") + _rows(12, 12, size="M")
    m = cap.build_capability_map(rows)
    out = so.apply_signoffs_to_map(m, [_signoff(size="*")], repo="todo")
    assert all(c.earned for c in out.cells)
    out2 = so.apply_signoffs_to_map(m, [_signoff(size="S")], repo="todo")
    assert out2.get(capability_class="frontend.component.add", size="S").earned
    assert not out2.get(capability_class="frontend.component.add", size="M").earned
    # a size-scoped attestation never lifts the class-level aggregate
    cm = cap.build_capability_map(rows, projection=cap.PROJECTION_CLASS)
    assert not so.apply_signoffs(cm.cells, [_signoff(size="S")], repo="todo")[0].earned


def test_signoff_does_not_change_the_route() -> None:
    m = cap.build_capability_map(_rows(5, 5))  # calibrate: n<10
    out = so.apply_signoffs(m.cells, [_signoff()], repo="todo")
    assert out[0].earned and out[0].route != ROUTE_DELIVER  # trust ≠ evidence


def test_load_and_apply_is_noop_without_ledger(tmp_path: Path) -> None:
    led = so.JsonlSignoffLedger(tmp_path / "missing.jsonl")
    assert list(led.records()) == [] and led.verify() == 0
    m = cap.build_capability_map(_rows(12, 12))
    assert so.apply_signoffs_to_map(m, led.records(), repo="todo") == m
