"""A damaged sealed set is quarantined and what cites it revoked — never reused (G-966).

Navigation
----------
What it is:   The suite for the recovery of a sealed dependency set that no longer matches its
              digest: the store's quarantine, the sealed provider's verify, the qualification
              store's revocation and the posture gate that joins them.
What it does: Pins that ``BundleStore.quarantine`` moves the set out of the store (a miss
              afterwards, never listed or mounted again) to ``.quarantine`` with a record of
              why and when; that ``SealedProvider.verify`` on a changed byte quarantines the
              set, emits ``provision.quarantined`` and raises ``BUNDLE_INTEGRITY`` naming the
              key; that ``revoke_citing`` appends a ``revoked`` record for every qualification
              in force whose bindings cite the key and leaves the others alone; that a run's
              ``context_for`` on a damaged set refuses, quarantines and revokes in the store
              and in the gate's own view, saying how many; that a resolve re-hashes a store
              hit and quarantines and reseals a damaged one rather than reuse it; and that the
              next seal of the same key succeeds — the product recovers, nobody deletes a
              directory by hand.
How:          A temp ``BundleStore`` filled through ``stage`` / ``seal``; SQLite ``init_db`` for
              the qualification store; the gate built with its store and stand-ins for the
              collaborators ``revoke_citing`` does not touch.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/provision/store.py (``quarantine``), src/crb/provision/__init__.py
              (``SealedProvider.verify``), src/crb/store/qualifications.py
              (``revoke_citing``), src/crb/server/posture_gate.py (``revoke_citing``)
Tested by:    tests/test_provision_quarantine.py
Touch when:   never for a new repository; the recovery from a damaged set changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from crb.core.deps import BUNDLE_INTEGRITY, DepsBinding, ProvisionRefused, TaskDeps
from crb.core.qualify import STATE_QUALIFIED, Qualification
from crb.core.spec import TaskSpec
from crb.provision import SealedProvider
from crb.provision.config import ProvisionConfig
from crb.provision.store import QUARANTINE, BundleStore
from crb.server.posture_gate import PostureGate
from crb.store import qualifications as sq
from crb.store.db import init_db, make_engine, make_session_factory

KEY = "dep_" + "d" * 64
OTHER = "dep_" + "e" * 64
P1 = "pst_" + "1" * 24


def _seal(store: BundleStore, key: str = KEY, data: bytes = b"x = 1\n") -> Path:
    st = store.stage()
    (st / "out" / "site").mkdir(parents=True)
    (st / "out" / "site" / "x.py").write_bytes(data)
    return store.seal(st, {"lang": "python", "key": key}).path


def _damage(path: Path) -> None:
    target = path / "site" / "x.py"
    target.chmod(0o644)
    target.write_bytes(b"x = 2\n")
    target.chmod(0o444)


def _deps(key: str = KEY) -> TaskDeps:
    return TaskDeps.uniform(DepsBinding(role="gold", lang="python", scheme="py.site.v1", key=key))


def _q(task_id: str, key: str) -> Qualification:
    return Qualification(
        qualification_id="",
        repo="calc",
        task_id=task_id,
        posture_id=P1,
        posture={"executor": "docker", "posture_class": "docker/copy/sealed", "image_ref": "img"},
        state=STATE_QUALIFIED,
        deps={"keys": [key], "mode": "sealed"},
        gold={"clean": True, "lint": None},
    )


def _factory(tmp_path: Path) -> sessionmaker[Any]:
    engine = make_engine(f"sqlite:///{tmp_path / 'crb.db'}")
    init_db(engine)
    return make_session_factory(engine)


def test_quarantine_moves_the_set_out_of_the_store_with_a_record(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "deps")
    path = _seal(store)
    moved = store.quarantine(KEY, "digest mismatch")
    assert not path.exists() and moved.is_dir()
    assert moved.parent == store.root / QUARANTINE / "python" and moved.name.startswith(KEY + ".")
    assert store.get("python", KEY) is None and store.find(KEY) is None and store.sets() == []
    (record,) = store.quarantined()
    assert (record["key"], record["lang"], record["reason"]) == (KEY, "python", "digest mismatch")
    assert record["digest_sealed"].startswith("sha256:") or record["digest_sealed"]
    with pytest.raises(KeyError):
        store.quarantine(KEY, "again")
    # the next run's seal of the same key succeeds: the product recovers on its own
    _seal(store)
    assert store.verify(KEY).key == KEY


def test_verify_quarantines_a_damaged_set_and_names_its_key(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "deps")
    _damage(_seal(store))
    events: list[tuple[str, dict[str, Any]]] = []
    provider = SealedProvider(
        ProvisionConfig(enabled=True, store=store.root, env="dev"),
        store=store,
        docker="docker",
        on_event=lambda a, p: events.append((a, dict(p))),
    )
    with pytest.raises(ProvisionRefused) as ei:
        provider.verify(_deps())
    assert ei.value.code == BUNDLE_INTEGRITY and ei.value.keys == (KEY,)
    assert (
        "moved to quarantine" in ei.value.message
        and "fetches and seals it afresh" in ei.value.message
    )
    assert store.find(KEY) is None and len(store.quarantined()) == 1
    assert [a for a, _ in events] == ["provision.quarantined"] and events[0][1]["key"] == KEY
    # a set that is simply absent is a miss, named but with nothing to move
    with pytest.raises(ProvisionRefused) as ei:
        provider.verify(_deps(OTHER))
    assert ei.value.keys == (OTHER,) and len(store.quarantined()) == 1


def test_revoke_citing_revokes_only_what_cites_the_key(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        sq.append(s, _q("a" * 40, KEY))
        sq.append(s, _q("b" * 40, OTHER))
        revoked = sq.revoke_citing(
            s, [KEY], BUNDLE_INTEGRITY, "worker", "digest mismatch", run_id="r1"
        )
        assert [q.task_id for q in revoked] == ["a" * 40]
        assert sq.latest(s, "calc", "a" * 40, P1).state == "revoked"  # type: ignore[union-attr]
        assert sq.latest(s, "calc", "a" * 40, P1).code == BUNDLE_INTEGRITY  # type: ignore[union-attr]
        assert sq.latest(s, "calc", "b" * 40, P1).state == STATE_QUALIFIED  # type: ignore[union-attr]
        # a second pass finds nothing in force to revoke
        assert sq.revoke_citing(s, [KEY], BUNDLE_INTEGRITY, "worker", "again") == []


def test_revoke_citing_revokes_in_the_store_and_in_the_gates_own_view(tmp_path: Path) -> None:
    """The seam alone, called directly: the run's path to it is pinned by
    ``test_a_run_that_meets_a_damaged_set_stops_quarantines_it_and_revokes_what_cites_it``."""
    factory = _factory(tmp_path)
    with factory() as s:
        sq.append(s, _q("a" * 40, KEY))
    events: list[tuple[str, dict[str, Any]]] = []
    stand_in: Any = object()
    gate = PostureGate(
        repo=stand_in,
        config=stand_in,
        runner=stand_in,
        executor=stand_in,
        scratch=tmp_path,
        provider=stand_in,
        posture=stand_in,
        run_id="r1",
        on_event=lambda a, p: events.append((a, dict(p))),
        session_factory=factory,
        actor="worker",
    )
    gate.qualifications["a" * 40] = _q("a" * 40, KEY)
    assert gate.revoke_citing([KEY], "digest mismatch") == 1
    assert (
        gate.qualifications["a" * 40].state == "revoked"
        and not gate.qualifications["a" * 40].is_qualified
    )
    assert events == [("provision.revoked", {"keys": [KEY], "revoked": 1})]
    with factory() as s:
        assert sq.latest(s, "calc", "a" * 40, P1).state == "revoked"  # type: ignore[union-attr]


def test_a_run_that_meets_a_damaged_set_stops_quarantines_it_and_revokes_what_cites_it(
    tmp_path: Path,
) -> None:
    """``recovery.23``, through the run's own path: the gate's ``context_for`` verifies the
    task's sealed set before any builder call, and on a changed byte it refuses
    ``BUNDLE_INTEGRITY``, the set is in quarantine, the store's record reads revoked and
    ``provision.revoked`` is emitted — nobody calls the revocation by hand."""
    factory = _factory(tmp_path)
    task_id = "a" * 40
    with factory() as s:
        sq.append(s, _q(task_id, KEY))
        sq.append(s, _q("b" * 40, OTHER))
    store = BundleStore(tmp_path / "deps")
    _damage(_seal(store))
    events: list[tuple[str, dict[str, Any]]] = []
    sink = lambda a, p: events.append((a, dict(p)))  # noqa: E731
    provider = SealedProvider(
        ProvisionConfig(enabled=True, store=store.root, env="dev"),
        store=store,
        docker="docker",
        on_event=sink,
    )
    stand_in: Any = object()
    gate = PostureGate(
        repo=stand_in,
        config=stand_in,
        runner=stand_in,
        executor=stand_in,
        scratch=tmp_path,
        provider=provider,
        posture=stand_in,
        run_id="r1",
        on_event=sink,
        session_factory=factory,
        actor="worker",
    )
    gate.qualifications[task_id] = _q(task_id, KEY)
    gate.qualifications["b" * 40] = _q("b" * 40, OTHER)
    gate._deps[task_id] = _deps()  # the task's bindings, as ``deps_for`` resolves them
    task = TaskSpec(
        task_id=task_id,
        repo="calc",
        subject="a change",
        authored="2026-09-01T00:00:00+00:00",
        test_files=("x_test.py",),
        src_files=("x.py",),
        target_tests=("x_test.py",),
        belt_scope=(),
    )
    with pytest.raises(ProvisionRefused) as ei:
        gate.context_for(task)
    assert ei.value.code == BUNDLE_INTEGRITY and ei.value.keys == (KEY,)
    assert store.find(KEY) is None and len(store.quarantined()) == 1
    assert [a for a, _ in events] == ["provision.quarantined", "provision.revoked"]
    assert events[1][1] == {"keys": [KEY], "revoked": 1}
    assert not gate.qualifications[task_id].is_qualified
    assert gate.qualifications["b" * 40].is_qualified
    with factory() as s:
        cut = sq.latest(s, "calc", task_id, P1)
        kept = sq.latest(s, "calc", "b" * 40, P1)
        assert cut is not None and (cut.state, cut.code) == ("revoked", BUNDLE_INTEGRITY)
        assert kept is not None and kept.state == STATE_QUALIFIED


def test_a_resolve_that_meets_a_damaged_set_quarantines_it_and_seals_it_afresh(
    tmp_path: Path,
) -> None:
    """The resolve path (``qualify`` and ``crb repo qualify``) never reuses a damaged set: a
    store hit is re-hashed, and one that fails its digest is moved to quarantine and fetched
    and sealed again — so an unloadable parent is not recorded unqualified on bad bytes."""
    store = BundleStore(tmp_path / "deps")
    _damage(_seal(store))
    events: list[tuple[str, dict[str, Any]]] = []
    provider = SealedProvider(
        ProvisionConfig(enabled=True, store=store.root, env="dev"),
        store=store,
        docker="docker",
        on_event=lambda a, p: events.append((a, dict(p))),
    )
    built: list[Path] = []

    def build(stage: Path) -> dict[str, Any]:
        built.append(stage)
        (stage / "out" / "site").mkdir(parents=True)
        (stage / "out" / "site" / "x.py").write_bytes(b"x = 1\n")
        return {}

    sealed = provider.seal_or_reuse("python", KEY, build)
    assert len(built) == 1
    assert [a for a, _ in events] == ["provision.quarantined", "provision.seal"]
    assert len(store.quarantined()) == 1 and store.verify(KEY).digest == sealed.digest
    # a whole set is reused as before, with no fetch
    events.clear()
    assert provider.seal_or_reuse("python", KEY, build).digest == sealed.digest
    assert len(built) == 1 and [a for a, _ in events] == ["provision.reuse"]


def test_crb_deps_verify_quarantine_moves_the_set_and_revokes_in_the_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Between runs the operator's verb does what a run does: the damaged set is moved aside
    and every qualification citing it is revoked, with the verb's own actor (G-966)."""
    from crb.cli.main import main

    factory = _factory(tmp_path)
    with factory() as s:
        sq.append(s, _q("a" * 40, KEY))
        sq.append(s, _q("b" * 40, OTHER))
    store = BundleStore(tmp_path / "deps")
    _damage(_seal(store))
    _seal(store, OTHER, b"y = 1\n")
    db = f"sqlite:///{tmp_path / 'crb.db'}"
    # without the flag: named, left in place, and the verb says how to recover
    assert main(["deps", "verify", "--store", str(store.root), "--database-url", db]) == 1
    assert "crb deps verify --quarantine" in capsys.readouterr().out
    assert store.find(KEY) is not None
    assert (
        main(["deps", "verify", "--quarantine", "--store", str(store.root), "--database-url", db])
        == 1
    )
    out = capsys.readouterr().out
    assert (
        f"FAIL {KEY}" in out
        and "never mounted again" in out
        and "revoked 1 qualification(s)" in out
    )
    assert (
        store.find(KEY) is None and store.find(OTHER) is not None and len(store.quarantined()) == 1
    )
    with factory() as s:
        cut = sq.latest(s, "calc", "a" * 40, P1)
        kept = sq.latest(s, "calc", "b" * 40, P1)
        assert cut is not None and (cut.state, cut.code) == ("revoked", BUNDLE_INTEGRITY)
        assert kept is not None and kept.state == STATE_QUALIFIED
    # the store is whole again: the next verify passes
    assert main(["deps", "verify", "--store", str(store.root)]) == 0
