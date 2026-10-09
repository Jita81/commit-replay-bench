"""``GET /ledger/verify`` serves the rising-disqualified stop condition (G-400, DL-312).

OPERATOR §8 names "a builder repeatedly disqualified for test tampering (shows as a rising
``disqualified`` count)" as a stop condition, and nothing served that count: an operator had
to export the ledger and count. ``verify`` now carries ``disqualified = {window_days,
threshold, by_builder: [{builder, n}], over: [builder]}`` — the block the Ledger's tile reads
— counted per builder over the last seven days, with DL-312's threshold and the builders at
or past it.

Navigation
----------
What it is:   The suite for the ``disqualified`` block of ``/ledger/verify``.
What it does: Appends disqualified rows through the ledger's own writer (the chain stays
              intact, so ``ok`` is what the seed makes it) and asserts the block: the window
              and threshold are the constants ``system.py`` declares, a builder with two
              disqualified rows in the window is ``over`` and one with one is not, a row older
              than the window is not counted, counts sort descending, and the block never
              changes ``ok``.
How:          ``make_env`` over the seed; ``DbLedger.append`` for the rows; one GET.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/routes/system.py (``disqualified_counts`` and the two constants),
              src/crb/server/routes/ledger.py (``verify_ledger`` serves the block),
              src/crb/server/schemas.py (``DisqualifiedOut``), docs/OPERATOR.md#8-stop-conditions
              (the number an operator reads), docs/DECISION-LOG.md (DL-312),
              tests/fixtures/server_seed.py (the seed), docs/dod/journeys/operate.md
              (journey-operate.recovery.17)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the window or the threshold changes (DL-312 says how
              — change the constant, this test and OPERATOR §8 together), or the served shape
              changes (the Ledger tile reads it: ui/src/screens/Ledger/LedgerPage.tsx).
"""

from __future__ import annotations

import datetime as _dt
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.ledger import GradeRow
from crb.server.routes.system import DISQUALIFIED_THRESHOLD, DISQUALIFIED_WINDOW_DAYS
from crb.store.ledger import DbLedger
from fixtures.posture import posture_row
from fixtures.server_seed import ALPHA, Env, make_env


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _disqualified(builder: str, *, days_ago: int = 0, task: str = "t") -> GradeRow:
    """A disqualified row (never clean) for ``builder``, created ``days_ago`` days back,
    with the posture labels a measured row of this apparatus must carry (ADR-0019)."""
    created = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days_ago)).isoformat(
        timespec="seconds"
    )
    return posture_row(
        repo=ALPHA,
        task_id=task,
        clean=False,
        tests_unmodified=False,
        target_green=True,
        no_new_failures=True,
        source_changed=True,
        builder=builder,
        model="m",
        disqualified=True,
        dq_reason="tests modified",
        created=created,
    )


def test_verify_serves_disqualified_by_builder_over_the_threshold(env: Env) -> None:
    """Two disqualified rows for ``tamperer`` inside the window put it ``over``; one row for
    ``honest`` does not; a row eight days old is outside the window and counts for nobody;
    the seed's own rows (none disqualified) contribute nothing; ``ok`` is untouched."""
    before = env.get("/ledger/verify").json()
    assert before["disqualified"] == {
        "window_days": DISQUALIFIED_WINDOW_DAYS,
        "threshold": DISQUALIFIED_THRESHOLD,
        "by_builder": [],
        "over": [],
    }
    assert DISQUALIFIED_WINDOW_DAYS == 7 and DISQUALIFIED_THRESHOLD == 2  # DL-312, OPERATOR §8
    ledger = DbLedger(env.factory)
    ledger.append(_disqualified("tamperer", task="t1"))
    ledger.append(_disqualified("tamperer", days_ago=6, task="t2"))
    ledger.append(_disqualified("honest", task="t3"))
    ledger.append(_disqualified("honest", days_ago=DISQUALIFIED_WINDOW_DAYS + 1, task="t4"))
    ledger.append(_disqualified("forgotten", days_ago=30, task="t5"))

    d = env.get("/ledger/verify").json()
    assert d["disqualified"] == {
        "window_days": 7,
        "threshold": 2,
        "by_builder": [{"builder": "tamperer", "n": 2}, {"builder": "honest", "n": 1}],
        "over": ["tamperer"],
    }
    # a count beside the chains, never a verdict on them
    assert d["ok"] == before["ok"] and d["chain_ok"] is True
    assert d["rows"] == before["rows"] + 5
