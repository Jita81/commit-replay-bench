"""The factory's entry gate reads routing.v2's registered readings, on one arm and one posture.

Navigation
----------
What it is:   The tests of the ONE binding between the factory's entry gate
              (``crb.factory.standard``) and the store's registered readings (ADR-0026 item 8).
What it does: Shows a reading whose ``S3`` and ``S1`` arms both deliver answers the ``S1``
              standard, unsigned until a sign-off made on that arm, class-set version, reading
              and apparatus covers it; a reading with no ``S3`` rows proves nothing; an ``S3``
              that alone delivers is a ceiling; another checks arm or posture class, or a
              licence read of another arm, answers nothing; a sign-off on another reading, or
              with no apparatus stamp, signs nothing.
How:          Pure: the readings, rows and sign-off records are built in memory and handed to
              ``readers_over`` / ``signed_by``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 2, 6 and 8)
Works with:   src/crb/server/factory_standard.py (under test), tests/fixtures/readings.py
              (sealed rows and registered readings), src/crb/core/signoff.py (the records a
              standard is signed by)
Tested by:    this file
Touch when:   never for a new repository; the binding's scope or the sign-off's binding changes.
"""

from __future__ import annotations

from dataclasses import replace

from crb.core.signoff import SignoffRecord
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.factory.standard import CellRef
from crb.server.factory_standard import readers_over, signed_by
from fixtures.readings import AUTHOR, CELL, REPO, S1, SEALED, commits, register_reading, rows_for

XS = CellRef("bug.fix", "XS")
POOL = commits(40)


def _world(s3: list[bool], s1: list[bool]) -> tuple[list, list]:
    reading = register_reading(POOL)
    rows = [
        *rows_for(s3, list(reading.pool), arm="S3"),
        *rows_for(s1, list(reading.pool), arm=S1),
    ]
    return [reading], rows


def test_both_arms_delivering_at_the_first_look_make_s1_the_standard() -> None:
    readings, rows = _world([True] * 20, [True] * 20)
    readers = readers_over(readings, rows, repo=REPO, checks_arm="off", posture_class=SEALED)
    std = readers.standard_for(XS)
    assert std is not None and std.arm == S1 and not std.ceiling and not std.signed
    assert std.reading_id == readings[0].reading_id
    arms = {a.arm: a for a in readers.arm_readings(XS)}
    assert arms["S3"].n == 20 and arms[S1].clean == 20
    # signed only by a sign-off the binding accepts
    signed = readers_over(
        readings,
        rows,
        repo=REPO,
        checks_arm="off",
        posture_class=SEALED,
        signed=lambda cell, arm, rid: arm == S1 and rid == readings[0].reading_id,
    )
    got = signed.standard_for(XS)
    assert got is not None and got.signed


def test_s1_rows_without_an_s3_reading_prove_nothing() -> None:
    readings, rows = _world([], [True] * 20)
    readers = readers_over(readings, rows, repo=REPO, checks_arm="off", posture_class=SEALED)
    assert readers.standard_for(XS) is None


def test_s3_alone_delivering_is_a_ceiling() -> None:
    readings, rows = _world([True] * 20, [True] * 17 + [False] * 3)
    readers = readers_over(readings, rows, repo=REPO, checks_arm="off", posture_class=SEALED)
    std = readers.standard_for(XS)
    assert std is not None and std.arm == "S3" and std.ceiling and not std.licenses


def test_another_checks_arm_posture_or_licence_arm_answers_nothing() -> None:
    readings, rows = _world([True] * 20, [True] * 20)
    assert (
        readers_over(
            readings, rows, repo=REPO, checks_arm="fmt", posture_class=SEALED
        ).standard_for(XS)
        is None
    )
    assert (
        readers_over(
            readings, rows, repo=REPO, checks_arm="off", posture_class="local/copy/net"
        ).standard_for(XS)
        is None
    )
    readers = readers_over(readings, rows, repo=REPO, checks_arm="off", posture_class=SEALED)
    licence = CellRef("bug.fix", "XS", CELL["builder"], CELL["model"], arm="S2")
    assert readers.standard_for(licence) is None
    same = readers.standard_for(replace(licence, arm=S1))
    assert same is not None and same.arm == S1
    # another builder's licence reads no reading of this cell
    assert readers.standard_for(CellRef("bug.fix", "XS", "other", "m", arm=S1)) is None


def _record(**kw: object) -> SignoffRecord:
    base: dict[str, object] = {
        "repo": REPO,
        "capability_class": "bug.fix",
        "size": "XS",
        "verifier": "approver-2",
        "apparatus_version": "2.4",
        "checks_arm": "off",
        "posture_class": SEALED,
        "context_arm": S1,
        "taxonomy": GLOBAL_CLASS_SET,
        "reading_id": "r" * 64,
    }
    base.update(kw)
    return SignoffRecord(**base)  # type: ignore[arg-type]


def test_a_sign_off_signs_only_its_arm_version_reading_and_apparatus() -> None:
    kw = {"arm": S1, "reading_id": "r" * 64, "checks_arm": "off", "posture_class": SEALED}
    assert signed_by([_record()], XS, apparatus="2.4", **kw)
    assert not signed_by([_record(reading_id="x" * 64)], XS, apparatus="2.4", **kw)
    assert not signed_by([_record(context_arm="S3")], XS, apparatus="2.4", **kw)
    assert not signed_by([_record(apparatus_version="")], XS, apparatus="2.4", **kw)  # GOV-6
    assert not signed_by([_record(apparatus_version="2.3")], XS, apparatus="2.4", **kw)
    assert not signed_by([_record(checks_arm="fmt")], XS, apparatus="2.4", **kw)
    assert not signed_by([_record(size="S")], XS, apparatus="2.4", **kw)
    revoked = [_record(), replace(_record(), revoked=True)]
    assert not signed_by(revoked, XS, apparatus="2.4", **kw)
    assert AUTHOR in S1
