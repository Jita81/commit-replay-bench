"""``POST /library/{repo}/mine`` over HTTP: the miners run on the clone at a pinned commit.

Navigation
----------
What it is:   Route tests of the miner routes of ``crb.server.routes.library`` on the seeded
              test app, with ``alpha``'s clone a real fixture repository.
What it does: Pins that a run pins the commit it names, appends each proposal under its miner
              (``mined:<name>@<version>``) with its file and commit, unsigned and unsponsored;
              that the run is a ``library.mined`` event naming the operator and each proposal a
              ``library.proposed`` event naming its miner; that the same sha proposes nothing
              and writes nothing new; that the change profile cites the seeded graded rows;
              that a mined proposal still needs one person to adopt it and another to sign it;
              that a credential a refused draft carried is neither stored nor echoed; and the
              refusals — an unknown miner, a commit the clone lacks, no clone.
How:          ``tests/fixtures/miner_repo.py`` builds the clone under ``<home>/repos/alpha``;
              ``fixtures.server_seed.make_env`` seeds the store with it as ``alpha``'s clone.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 10)
Works with:   src/crb/server/routes/library.py (the routes under test), src/crb/core/miners.py
              (the run), tests/fixtures/miner_repo.py (the clone), tests/fixtures/server_seed.py
              (the accounts, the repository and its graded rows)
Tested by:    this file
Touch when:   never for a new repository; a miner route, its body or its events change.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from crb.store.models import Event, LibraryActRow
from fixtures.miner_repo import FILES, MinerRepo, commit, make_miner_repo
from fixtures.server_seed import ALPHA, Env, envelope, login, logout, make_env, user_id

#: The seeded tasks change ``src/pkg/m<i>.py``: the clone carries that part so the change
#: profile can name it.
_CLONE_FILES = {**FILES, "src/pkg/__init__.py": "", "src/pkg/m1.py": "X = 1\n"}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def clone(tmp_path: Path) -> MinerRepo:
    return make_miner_repo(tmp_path / "repos" / ALPHA, _CLONE_FILES)


@pytest.fixture
def env(tmp_path: Path, clone: MinerRepo) -> Iterator[Env]:
    with make_env(tmp_path, clone_path=str(clone.path), role="operator") as e:
        yield e


def _events(env: Env, action: str) -> list[Event]:
    with env.factory() as s:
        return list(
            s.execute(select(Event).where(Event.action == action).order_by(Event.id)).scalars()
        )


def _acts(env: Env) -> int:
    with env.factory() as s:
        return len(list(s.execute(select(LibraryActRow.seq)).scalars()))


def test_a_run_pins_its_commit_and_proposes_under_each_miner_unsigned(
    env: Env, clone: MinerRepo
) -> None:
    r = env.post(f"/library/{ALPHA}/mine", json={"commit": "main"})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["commit"] == clone.sha and run["reaches_briefs"] is False
    assert run["miners"] == ["adrs@1", "owners@1", "lint@2", "tests@1", "change-profile@1"]
    got = {e["entry_id"]: e for e in run["proposed"]}
    assert run["counts"]["proposed"] == len(got) > 0
    adr = got["decision/adr-0001-use-go-modules-for-every-command"]
    assert adr["entry"]["proposed_by"] == "mined:adrs@1"
    assert adr["entry"]["provenance"]["path"] == "docs/adr/0001-use-go-modules.md"
    assert adr["entry"]["provenance"]["commit"] == clone.sha
    for e in got.values():
        assert (e["status"], e["sponsor"], e["approver"]) == ("proposed", "", "")
        assert e["entry"]["proposed_by"].startswith("mined:")
    # the change profile cites the seeded graded rows of bug.fix in src/pkg
    wt = got["work-type/bug-fix-in-src-pkg"]
    assert wt["entry"]["provenance"]["kind"] == "rows" and wt["entry"]["provenance"]["rows"]
    assert wt["entry"]["parent_class"] == "bug.fix"
    # the index serves them as the library's own entries
    index = {e["entry_id"] for e in env.get(f"/library/{ALPHA}").json()["entries"]}
    assert set(got) <= index


def test_the_run_is_an_event_naming_the_operator_and_each_proposal_its_miner(
    env: Env, clone: MinerRepo
) -> None:
    run = env.post(f"/library/{ALPHA}/mine", json={"miners": ["lint"]}).json()
    [mined] = _events(env, "library.mined")
    assert mined.actor == user_id("op1") and mined.repo == ALPHA
    assert mined.payload_json["commit"] == clone.sha
    assert mined.payload_json["miners"] == ["lint@2"]
    assert mined.payload_json["proposed"] == [e["entry_id"] for e in run["proposed"]]
    proposed = _events(env, "library.proposed")
    assert {e.actor for e in proposed} == {"mined:lint@2"}
    assert {e.payload_json["run_by"] for e in proposed} == {user_id("op1")}
    assert {e.payload_json["commit"] for e in proposed} == {clone.sha}


def test_the_same_sha_proposes_nothing_and_writes_no_act(env: Env, clone: MinerRepo) -> None:
    first = env.post(f"/library/{ALPHA}/mine", json={}).json()
    written = _acts(env)
    assert written == first["counts"]["proposed"]
    again = env.post(f"/library/{ALPHA}/mine", json={"commit": clone.sha}).json()
    assert again["proposed"] == [] and again["counts"]["proposed"] == 0
    assert again["counts"]["unchanged"] == first["counts"]["proposed"]
    assert _acts(env) == written
    # a new commit that changes one configuration proposes that entry alone again
    commit(clone.path, {".golangci.yml": "linters:\n  enable: [govet, errcheck]\n"}, "lint")
    third = env.post(f"/library/{ALPHA}/mine", json={}).json()
    assert [e["entry_id"] for e in third["proposed"]] == ["convention/golangci-lint"]


def test_a_mined_proposal_needs_a_person_to_adopt_it_and_another_to_sign_it(env: Env) -> None:
    run = env.post(f"/library/{ALPHA}/mine", json={"miners": ["lint"]}).json()
    ruff = next(e for e in run["proposed"] if e["entry_id"] == "convention/ruff")
    logout(env.client)
    login(env.client, "approver")
    r = env.post(
        f"/library/{ALPHA}/entries/convention/ruff/sign", json={"version": ruff["version"]}
    )
    assert r.status_code == 409 and envelope(r)["detail"]["code"] == "no_sponsor"
    logout(env.client)
    login(env.client, "operator")
    r = env.post(
        f"/library/{ALPHA}/entries/convention/ruff/sponsor", json={"version": ruff["version"]}
    )
    assert r.status_code == 200 and r.json()["sponsor"] == user_id("op1")
    logout(env.client)
    login(env.client, "approver")
    r = env.post(
        f"/library/{ALPHA}/entries/convention/ruff/sign", json={"version": ruff["version"]}
    )
    assert r.status_code == 200 and r.json()["status"] == "signed"


def test_the_registry_is_served_in_the_order_a_run_applies_it(env: Env) -> None:
    r = env.get(f"/library/{ALPHA}/miners")
    assert r.status_code == 200, r.text
    miners = r.json()["miners"]
    assert [m["name"] for m in miners] == ["adrs", "owners", "lint", "tests", "change-profile"]
    assert miners[0]["proposer"] == "mined:adrs@1" and miners[0]["kinds"] == ["decision"]


def test_an_unknown_miner_or_a_commit_the_clone_lacks_is_refused_and_writes_nothing(
    env: Env,
) -> None:
    r = env.post(f"/library/{ALPHA}/mine", json={"miners": ["nobody"]})
    assert r.status_code == 422 and "no miner registered as nobody" in envelope(r)["message"]
    r = env.post(f"/library/{ALPHA}/mine", json={"commit": "0" * 40})
    assert r.status_code == 422 and envelope(r)["code"] == "unknown_commit"
    r = env.post(f"/library/{ALPHA}/mine", json={"commit": "--upload-pack=x"})
    assert r.status_code == 422  # never an option to git
    assert _acts(env) == 0 and _events(env, "library.mined") == []


def test_a_credential_in_a_refused_draft_is_neither_stored_nor_echoed(
    env: Env, clone: MinerRepo
) -> None:
    key = "sk-proj-abcdefghijklmnopqrstuvwx1234"
    commit(clone.path, {f"docs/adr/0009-rotate-{key}.md": f"# 9. Rotate {key}\n\n"
                        "Status: accepted\n\n## Decision\n\nRotate it.\n"}, "adr 9")  # fmt: skip
    r = env.post(f"/library/{ALPHA}/mine", json={"miners": ["adrs"]})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["refused"] == 1
    assert key not in r.text
    [mined] = _events(env, "library.mined")
    assert key not in str(mined.payload_json)
    with env.factory() as s:
        bodies = [str(b) for b in s.execute(select(LibraryActRow.body_json)).scalars()]
    assert all(key not in b for b in bodies)


def test_a_repository_with_no_clone_cannot_be_mined(tmp_path: Path) -> None:
    with make_env(tmp_path, role="operator") as env:
        r = env.post(f"/library/{ALPHA}/mine", json={})
        assert r.status_code == 409 and envelope(r)["code"] == "no_clone_path"
