"""The class sets in the store: acts checked and chained at write, labels appended, never edited.

Navigation
----------
What it is:   Tests of ``crb.store.class_sets.DbClassSets`` on a fresh SQLite store.
What it does: Pins that an act is checked against the organisation's versions inside the write
              (a refused act writes nothing), that every act is chained on the one sequence and
              the chain verifies and catches a tampered row, that the tables refuse an UPDATE,
              and that the label table's latest rule label per commit is the one read.
How:          ``init_db`` on a temporary SQLite file; acts from ``tests/fixtures/class_sets.py``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9),
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/class_sets.py (under test), src/crb/core/class_sets.py (the rule),
              tests/fixtures/class_sets.py (the organisation)
Tested by:    this file
Touch when:   never for a new repository; a reading of the acts or labels is added.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from crb.core import class_sets as cs
from crb.core.ledger import LedgerIntegrityError
from crb.core.library import LibraryRefused
from crb.store.class_sets import DbClassSets, new_act
from crb.store.db import init_db
from fixtures.class_sets import APPROVER, ORG, REPO, SPONSOR, version


@pytest.fixture
def store(tmp_path: Path) -> DbClassSets:
    engine = create_engine(f"sqlite:///{tmp_path / 'classes.db'}")
    init_db(engine)
    return DbClassSets(sessionmaker(bind=engine))


def _factory(store: DbClassSets) -> sessionmaker[Session]:
    return store._factory


def test_acts_are_checked_at_write_chained_and_verified(store: DbClassSets) -> None:
    v = version()
    store.append(
        new_act(ORG, v.version_id, v.digest, cs.ACT_PROPOSE, SPONSOR, body={"version": v.content()})
    )
    with pytest.raises(LibraryRefused):
        store.append(new_act(ORG, v.version_id, v.digest, cs.ACT_SIGN, SPONSOR))
    assert len(store.acts()) == 1  # the refused signature wrote nothing
    _chained, state = store.append(new_act(ORG, v.version_id, v.digest, cs.ACT_SIGN, APPROVER))
    assert state.signed and store.versions(ORG)[v.version_id].approver == APPROVER
    assert store.orgs() == [ORG] and store.verify() == 2
    with _factory(store)() as s, pytest.raises(DBAPIError, match="append-only"):
        s.execute(text("UPDATE class_set_acts SET actor = 'x'"))
        s.commit()


def test_a_tampered_act_breaks_the_chain(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'raw.db'}")
    init_db(engine)
    store = DbClassSets(sessionmaker(bind=engine))
    v = version()
    store.append(
        new_act(ORG, v.version_id, v.digest, cs.ACT_PROPOSE, SPONSOR, body={"version": v.content()})
    )
    with engine.begin() as c:  # drop the trigger the way an attacker with the file would
        c.execute(text("DROP TRIGGER class_set_acts_no_update"))
        c.execute(text("UPDATE class_set_acts SET actor = :x"), {"x": APPROVER})
    with pytest.raises(LedgerIntegrityError):
        store.verify()


def test_the_label_table_is_appended_and_its_latest_rule_label_read(store: DbClassSets) -> None:
    v1 = "acme/classes@v1"
    assert (
        store.add_labels(v1, [(REPO, "a" * 40, "parser-fix")], source="rule", labeller=SPONSOR) == 1
    )
    store.add_labels(v1, [(REPO, "a" * 40, "cli-fix")], source="rule", labeller=SPONSOR)
    store.add_labels(v1, [(REPO, "a" * 40, "chore")], source="person", labeller=APPROVER)
    assert store.rule_labels(v1, REPO) == {(REPO, "a" * 40): "cli-fix"}
    assert [r.capability_class for r in store.labels(v1, source="person")] == ["chore"]
    with _factory(store)() as s, pytest.raises(DBAPIError, match="append-only"):
        s.execute(text("DELETE FROM class_labels"))
        s.commit()
