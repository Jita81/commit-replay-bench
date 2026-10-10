"""``/classes`` over HTTP: a sponsor proposes, a person labels, the report reads, another signs.

Navigation
----------
What it is:   Route tests of ``crb.server.routes.classes`` (and the class-set guard of
              ``POST /readings``) on the seeded test app, over the fixture organisation ``acme``
              whose 200 synthetic commits are added to the ``alpha`` repository.
What it does: Walks a version from proposal (an operator, its sponsor; every commit relabelled
              into the label table, no ledger row touched) through a person's blind labels of
              derivation commits (a confirmation commit is refused 409 ``confirmation_commit``;
              the queue carries no rule label, no other person's label and no outcome) and the
              validity report, to a signature by an approver who is not the sponsor (the sponsor
              is refused 409 ``same_person``); pins that an unsigned or failing version routes
              nothing and a signed passing one routes; reads the class page in plain words
              (example commits from the derivation set only, what a ticket carries, the library's
              context, "no proven standard" and the next measurement per size); proposes version
              N+1 from a signed library work-type entry (the DL-044 seam) and refuses a rule
              whose component the library does not name; pins every role gate and event; and
              registers a reading of an organisation class only over its confirmation commits,
              refused while the version does not route or on a cell that is not its parent's;
              pins that the sponsor is offered nothing to label, that a class's example commits
              are never offered, that the agreement is withheld from a person part-way through
              their sample, that one organisation's class sets describe a repository, that a
              backlog item cannot carry an organisation's class by hand, and that a refusal names
              the class it is about.
How:          ``fixtures.server_seed.make_env`` (SQLite, the four role accounts, ``alpha``), the
              fixture organisation's commits inserted as ``Task`` rows, ``login`` per role.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9)
Works with:   src/crb/server/routes/classes.py (the routes under test),
              src/crb/server/class_set_state.py (the report and the relabel),
              src/crb/server/routes/readings.py (the reading's pool guard),
              tests/fixtures/class_sets.py (the organisation), tests/fixtures/server_seed.py
              (the app, the accounts and the repository)
Tested by:    this file
Touch when:   never for a new repository; a route, a field or an act of ``/classes`` changes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.class_sets import split_of
from crb.store.class_sets import DbClassSets
from crb.store.models import ClassLabelRow, Event, Grade, Task
from fixtures.class_sets import add_commits, sha
from fixtures.proven import AUTHOR, S1
from fixtures.readings import SEALED
from fixtures.server_seed import (
    ALPHA,
    BUILDER,
    MODEL,
    PROVIDER,
    Env,
    assert_rbac,
    envelope,
    login,
    logout,
    make_env,
    user_id,
)

ORG = "acme"
V1 = "acme/classes@v1"
PARSER = {
    "slug": "parser-fix",
    "title": "A fix to the parser",
    "definition": "A change that corrects how the parser reads its input; the ticket names the parser.",
    "parent": "bug.fix",
    "rule": {"words": ["parser", "parse"]},
}
CLI = {
    "slug": "cli-fix",
    "title": "A fix to the command line",
    "definition": "A change that corrects the command line's flags or output.",
    "parent": "bug.fix",
    "rule": {"words": ["cli", "flag"]},
}
CHORE = {
    "slug": "chore",
    "title": "Housekeeping",
    "definition": "Version bumps, fixes of the seed's own tasks and other housekeeping.",
    "parent": "docs.update",
    "rule": {"words": ["chore", "task"]},
}
CELL = {
    "process_step": "replay",
    "capability_class": "bug.fix",
    "size": "S",
    "language": "python",
    "builder": BUILDER,
    "model": MODEL,
    "provider": PROVIDER,
}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path, role="operator") as e:
        add_commits(e.factory)
        yield e


def _as(env: Env, role: str) -> None:
    logout(env.client)
    login(env.client, role)


def _propose(
    env: Env, *classes: dict[str, Any], repos: tuple[str, ...] = (ALPHA,)
) -> dict[str, Any]:
    r = env.post(f"/classes/{ORG}/versions", json={"repos": list(repos), "classes": list(classes)})
    assert r.status_code == 201, r.text
    return dict(r.json())


def _events(env: Env, prefix: str = "class_set.") -> list[Event]:
    with env.factory() as s:
        return list(
            s.execute(select(Event).where(Event.action.like(f"{prefix}%")).order_by(Event.id))
            .scalars()
            .all()
        )


def _label_all(env: Env, n: int = 1, *, role: str = "admin", back: str = "operator") -> int:
    """As ``role`` (never the sponsor), label every derivation commit version ``n`` offers as
    the rule would (the person agrees), then sign back in as ``back``."""
    _as(env, role)
    queue = env.get(f"/classes/{ORG}/v/{n}/label-queue").json()
    assert queue["sponsor"] is False, "the sponsor is offered nothing to label"
    rule = {"parser": "parser-fix", "parse": "parser-fix", "cli": "cli-fix", "flag": "cli-fix"}
    done = 0
    for item in queue["items"]:
        words = item["message"].replace("--", " ").split()
        klass = next((rule[w] for w in words if w in rule), "chore")
        r = env.post(
            f"/classes/{ORG}/v/{n}/labels",
            json={"repo": item["repo"], "task_id": item["task_id"], "class": klass},
        )
        assert r.status_code == 201, r.text
        done += 1
    _as(env, back)
    return done


def test_a_sponsor_proposes_and_every_commit_is_relabelled_without_touching_a_row(env: Env) -> None:
    with env.factory() as s:
        before = [(g.row_hash, g.capability_class) for g in s.execute(select(Grade)).scalars()]
    v = _propose(env, PARSER, CLI, CHORE)
    assert (v["version_id"], v["status"], v["n"]) == (V1, "proposed", 1)
    assert v["sponsor"] == user_id("op1") and v["sponsor_name"] == "op1"
    assert v["route"]["routes"] is False and v["route"]["code"] == "class_set_unsigned"
    assert v["version"]["derivation_share"] == pytest.approx(1 / 3)
    assert v["version"]["split_seed"] == "crb.split.v1"
    with env.factory() as s:
        n_tasks = len(list(s.execute(select(Task).where(Task.repo == ALPHA)).scalars()))
        after = [(g.row_hash, g.capability_class) for g in s.execute(select(Grade)).scalars()]
        labels = list(s.execute(select(ClassLabelRow)).scalars())
    assert after == before  # a relabel never rewrites a stored ledger row
    assert len(labels) == n_tasks and {x.source for x in labels} == {"rule"}
    rule = DbClassSets(env.factory).rule_labels(V1, ALPHA)
    assert rule[(ALPHA, sha(1))] == "parser-fix" and rule[(ALPHA, sha(0))] == "cli-fix"
    actions = [(e.action, e.actor) for e in _events(env)]
    assert actions == [
        ("class_set.proposed", user_id("op1")),
        ("class_set.relabelled", user_id("op1")),
    ]
    detail = env.get(f"/classes/{ORG}/v/1").json()
    split = {x["repo"]: x for x in detail["split"]}[ALPHA]
    with env.factory() as s:
        ids = list(s.execute(select(Task.task_id).where(Task.repo == ALPHA)).scalars())
    assert split["derivation"] == sum(1 for t in ids if split_of(ALPHA, t) == "derivation")
    assert split["derivation"] + split["confirmation"] == n_tasks


def test_the_sponsor_cannot_sign_and_a_second_person_can(env: Env) -> None:
    _as(env, "admin")
    v = _propose(env, PARSER, CLI, CHORE)
    r = env.post(f"/classes/{ORG}/v/1/sign", json={"digest": v["digest"]})
    assert r.status_code == 409, r.text
    err = envelope(r)
    assert (err["code"], err["detail"]["code"]) == ("class_set_refused", "same_person")
    assert "second person" in err["message"]
    refused = [e for e in _events(env) if e.action == "class_set.refused"]
    assert len(refused) == 1 and refused[0].payload_json["code"] == "same_person"
    _as(env, "approver")
    stale = env.post(f"/classes/{ORG}/v/1/sign", json={"digest": "0" * 64})
    assert envelope(stale)["detail"]["code"] == "version_mismatch"
    r = env.post(f"/classes/{ORG}/v/1/sign", json={"digest": v["digest"]})
    assert r.status_code == 200, r.text
    signed = r.json()
    assert (signed["status"], signed["approver_name"]) == ("signed", "appr1")
    # signed, but no person has labelled anything: the report fails and it routes nothing
    assert signed["route"] == {
        "routes": False,
        "code": "class_set_report_failed",
        "words": signed["route"]["words"],
    }
    assert "agreement" in signed["route"]["words"]
    assert env.get("/classes/verify").json()["ok"] is True


def test_the_labelling_screen_is_blind_and_takes_derivation_commits_only(env: Env) -> None:
    _as(env, "approver")
    _propose(env, PARSER, CLI, CHORE)  # appr1 sponsors it
    # the sponsor is offered nothing, and their own label is refused: the rule is their words
    own = env.get(f"/classes/{ORG}/v/1/label-queue").json()
    assert (own["sponsor"], own["items"]) == (True, [])
    r = env.post(
        f"/classes/{ORG}/v/1/labels", json={"repo": ALPHA, "task_id": sha(1), "class": "cli-fix"}
    )
    assert r.status_code == 409 and envelope(r)["detail"]["code"] == "sponsor_label"
    # another person's label is never shown to this one
    _as(env, "admin")
    queue = env.get(f"/classes/{ORG}/v/1/label-queue").json()
    first = queue["items"][0]
    assert (
        env.post(
            f"/classes/{ORG}/v/1/labels",
            json={"repo": ALPHA, "task_id": first["task_id"], "class": "cli-fix"},
        ).status_code
        == 201
    )
    _as(env, "operator")
    queue = env.get(f"/classes/{ORG}/v/1/label-queue").json()
    assert {c["slug"] for c in queue["classes"]} == {"parser-fix", "cli-fix", "chore"}
    for item in queue["items"]:
        assert split_of(ALPHA, item["task_id"]) == "derivation"
        assert set(item) == {"repo", "task_id", "message", "ticket", "diff", "my_label"}
        assert item["my_label"] == ""  # the admin's label is not this person's
        assert set(item["diff"]) == {"source_files", "test_files", "churn"}
    # no commit a class's page shows as the rule's example is ever offered, or taken (P-686)
    shown = {
        x["sha"]
        for slug in ("parser-fix", "cli-fix", "chore")
        for x in env.get(f"/classes/{ORG}/v/1/classes/{slug}").json()["examples"]
    }
    assert shown and not shown & {x["task_id"] for x in queue["items"]}
    r = env.post(
        f"/classes/{ORG}/v/1/labels",
        json={"repo": ALPHA, "task_id": sorted(shown)[0], "class": "cli-fix"},
    )
    assert r.status_code == 409 and envelope(r)["detail"]["code"] == "example_commit"
    # a confirmation commit is refused, with a reason, and the refusal is recorded
    confirming = next(sha(i) for i in range(200) if split_of(ALPHA, sha(i)) == "confirmation")
    r = env.post(
        f"/classes/{ORG}/v/1/labels",
        json={"repo": ALPHA, "task_id": confirming, "class": "cli-fix"},
    )
    assert r.status_code == 409 and envelope(r)["detail"]["code"] == "confirmation_commit"
    bad = env.post(
        f"/classes/{ORG}/v/1/labels",
        json={"repo": ALPHA, "task_id": first["task_id"], "class": "nope"},
    )
    assert bad.status_code == 422
    ok = env.post(
        f"/classes/{ORG}/v/1/labels",
        json={"repo": ALPHA, "task_id": first["task_id"], "class": "(unclassified)"},
    )
    assert ok.status_code == 201 and ok.json()["labeller"] == user_id("op1")
    labelled = [e for e in _events(env) if e.action == "class_set.labelled"]
    assert [e.actor for e in labelled] == [user_id("root"), user_id("op1")]
    refused = [e.payload_json["code"] for e in _events(env) if e.action == "class_set.refused"]
    assert refused == ["sponsor_label", "example_commit", "confirmation_commit"]


def test_a_signed_version_whose_report_passes_routes_and_its_class_page_reads_in_plain_words(
    env: Env,
) -> None:
    v = _propose(env, PARSER, CLI, CHORE)
    labelled = _label_all(env)
    assert labelled >= 50
    detail = env.get(f"/classes/{ORG}/v/1").json()
    measures = {m["name"]: m for m in detail["report"]["measures"]}
    assert measures["agreement"]["value"] == pytest.approx(1.0)
    assert measures["coverage"]["state"] == "pass"
    assert detail["report"]["passes"] is True
    assert detail["route"]["code"] == "class_set_unsigned"  # passing, but not signed yet
    _as(env, "approver")
    signed = env.post(f"/classes/{ORG}/v/1/sign", json={"digest": v["digest"]}).json()
    assert signed["route"]["routes"] is True
    page = env.get(f"/classes/{ORG}/v/1/classes/parser-fix").json()
    assert page["definition"].startswith("A change that corrects how the parser")
    assert page["parent"] == "bug.fix"
    assert (
        page["rule_words"]
        == "A ticket is in this class when the ticket's text says “parser” or “parse”."
    )
    assert page["examples"] and all(
        split_of(x["repo"], x["sha"]) == "derivation" for x in page["examples"]
    )
    assert all(
        x["proxy"] for x in page["examples"]
    )  # no linked-ticket reader: the message stands in
    assert {s["name"] for s in page["ticket_slots"]}  # the readiness slots of the parent
    assert page["library"] == [{"repo": ALPHA, "work_type": "bug.fix"}]
    s_cell = next(x for x in page["sizes"] if x["size"] == "S")
    assert s_cell["standard"] is None and s_cell["confirmation"] > 20
    assert "Register a reading of this class" in s_cell["next"]
    # revoked, it routes nothing again
    r = env.post(f"/classes/{ORG}/v/1/revoke", json={"reason": "the parser team split"})
    assert r.status_code == 200 and r.json()["route"]["code"] == "class_set_revoked"
    assert [e.action for e in _events(env)][-2:] == ["class_set.signed", "class_set.revoked"]


def test_a_ceiling_never_reads_signed_on_the_class_page(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-411: the class page reads "signed" by the gate's own clause (``standard_signed``),
    not the bound standard's raw flag — so ``S3``, a ceiling that licenses nothing, never
    reads signed there, whatever a sign-off record says."""
    from crb.factory.standard import Readers, Standard
    from crb.server import factory_standard

    ceiling = Standard("S3", signed=True, reading_id="r-ceiling")
    monkeypatch.setattr(
        factory_standard, "readers_in", lambda *a, **k: Readers(standard_for=lambda c: ceiling)
    )
    _propose(env, PARSER, CLI, CHORE)
    page = env.get(f"/classes/{ORG}/v/1/classes/parser-fix").json()
    standards = [x["standard"] for x in page["sizes"]]
    assert standards and all(s["ceiling"] is True and s["signed"] is False for s in standards)


def test_versions_are_numbered_and_the_index_lists_them(env: Env) -> None:
    _propose(env, PARSER, CLI)
    v2 = _propose(env, PARSER, CLI, CHORE)
    assert v2["version_id"] == "acme/classes@v2" and v2["version"]["based_on"] == V1
    index = env.get("/classes").json()
    assert [o["org"] for o in index["orgs"]] == ["acme"]
    assert [v["n"] for v in index["orgs"][0]["versions"]] == [2, 1]
    assert index["thresholds"]["kappa_min"] == 0.6 and index["thresholds"]["sample_min"] == 50


def test_a_rule_names_only_the_organisations_signed_components(env: Env) -> None:
    bad = {**PARSER, "rule": {"components": ["billing"]}}
    r = env.post(f"/classes/{ORG}/versions", json={"repos": [ALPHA], "classes": [bad]})
    assert r.status_code == 422 and "not a signed component" in envelope(r)["message"]
    component = {
        "kind": "component",
        "slug": "billing",
        "title": "Billing",
        "statement": "The billing part.",
    }
    proposed = env.post(f"/library/{ALPHA}/entries", json=component).json()
    _as(env, "approver")
    env.post(
        f"/library/{ALPHA}/entries/component/billing/sign", json={"version": proposed["version"]}
    )
    _as(env, "operator")
    r = env.post(f"/classes/{ORG}/versions", json={"repos": [ALPHA], "classes": [bad]})
    assert r.status_code == 201, r.text


def test_a_using_team_adds_a_class_as_a_signed_work_type_entry_the_dl_044_seam(env: Env) -> None:
    _propose(env, PARSER, CLI)
    # nothing new in the library yet: refused with what to do
    r = env.post(f"/classes/{ORG}/versions/from-library", json={"repos": [ALPHA], "rules": {}})
    assert r.status_code == 422 and "sign one in the library" in envelope(r)["message"]
    entry = {
        "kind": "work-type",
        "slug": "lexer-fix",
        "title": "A fix to the lexer",
        "statement": "A change that corrects how source text is split into tokens.",
        "parent_class": "bug.fix",
    }
    proposed = env.post(f"/library/{ALPHA}/entries", json=entry).json()
    # proposed but not signed, the entry is not a class: neither from the library nor by name
    unsigned = env.post(
        f"/classes/{ORG}/versions/from-library",
        json={"repos": [ALPHA], "rules": {"lexer-fix": {"words": ["lexer"]}}},
    )
    assert (
        unsigned.status_code == 422 and "sign one in the library" in envelope(unsigned)["message"]
    )
    by_name = env.post(
        f"/classes/{ORG}/versions",
        json={"repos": [ALPHA], "classes": [PARSER, {"entry_repo": ALPHA,
              "entry_slug": "lexer-fix", "rule": {"words": ["lexer"]}}]},
    )  # fmt: skip
    assert by_name.status_code == 422
    assert "has no signed work-type entry 'lexer-fix'" in envelope(by_name)["message"]
    assert [v["n"] for v in env.get("/classes").json()["orgs"][0]["versions"]] == [1]
    _as(env, "approver")
    env.post(
        f"/library/{ALPHA}/entries/work-type/lexer-fix/sign", json={"version": proposed["version"]}
    )
    _as(env, "operator")
    missing = env.post(
        f"/classes/{ORG}/versions/from-library", json={"repos": [ALPHA], "rules": {}}
    )
    assert missing.status_code == 422 and "needs its rule" in envelope(missing)["message"]
    r = env.post(
        f"/classes/{ORG}/versions/from-library",
        json={"repos": [ALPHA], "rules": {"lexer-fix": {"words": ["lexer", "token"]}}},
    )
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["version_id"] == "acme/classes@v2" and v2["version"]["based_on"] == V1
    slugs = [c["slug"] for c in v2["version"]["classes"]]
    assert slugs == ["parser-fix", "cli-fix", "lexer-fix"]
    # version N+1 is proposed, not routing, and its sponsor still cannot sign it
    assert (v2["status"], v2["route"]["code"]) == ("proposed", "class_set_unsigned")
    assert v2["sponsor"] == user_id("op1")  # its sponsor; the next test pins same_person
    lexer = v2["version"]["classes"][2]
    assert (lexer["entry_id"], lexer["entry_repo"], lexer["parent"]) == (
        "work-type/lexer-fix",
        ALPHA,
        "bug.fix",
    )
    assert lexer["definition"] == entry["statement"]
    page = env.get(f"/classes/{ORG}/v/2/classes/lexer-fix").json()
    assert page["library"] == [{"repo": ALPHA, "work_type": "lexer-fix"}]


def test_every_route_is_role_gated(env: Env) -> None:
    body = {"repos": [ALPHA], "classes": [PARSER]}
    assert_rbac(env, "GET", "/classes", min_role="viewer")
    assert_rbac(env, "POST", f"/classes/{ORG}/versions", min_role="operator", json=body)
    assert_rbac(env, "GET", f"/classes/{ORG}/v/1", min_role="viewer")
    assert_rbac(env, "GET", f"/classes/{ORG}/v/1/classes/parser-fix", min_role="viewer")
    assert_rbac(env, "GET", f"/classes/{ORG}/v/1/label-queue", min_role="operator")
    assert_rbac(
        env, "POST", f"/classes/{ORG}/v/1/labels", min_role="operator",
        json={"repo": ALPHA, "task_id": sha(0), "class": "parser-fix"},
    )  # fmt: skip
    assert_rbac(
        env, "POST", f"/classes/{ORG}/v/1/sign", min_role="approver", json={"digest": "0" * 64}
    )
    assert_rbac(
        env, "POST", f"/classes/{ORG}/v/1/revoke", min_role="approver", json={"reason": "x"}
    )
    assert_rbac(
        env, "POST", f"/classes/{ORG}/versions/from-library", min_role="operator",
        json={"repos": [ALPHA], "rules": {}},
    )  # fmt: skip
    assert_rbac(env, "GET", "/classes/verify", min_role="viewer")


def test_a_reading_of_an_organisation_class_reads_confirmation_commits_only(env: Env) -> None:
    v = _propose(env, PARSER, CLI, CHORE)
    body = {
        "repo": ALPHA,
        "cell": CELL,
        "hierarchy": ["S3", S1],
        "posture_class": SEALED,
        "author_model": AUTHOR,
        "taxonomy": V1,
        "org_class": "parser-fix",
    }
    # unsigned: the version routes nothing, so no reading of its classes is registered
    r = env.post("/readings", json=body)
    assert r.status_code == 409, r.text
    assert envelope(r)["code"] == "class_set_not_routing"
    # a class set is read one class at a time
    assert env.post("/readings", json={**body, "org_class": ""}).status_code == 422
    _label_all(env)
    _as(env, "approver")
    env.post(f"/classes/{ORG}/v/1/sign", json={"digest": v["digest"]})
    _as(env, "operator")
    r = env.post("/readings", json=body)
    assert r.status_code == 201, r.text
    reading = r.json()
    assert reading["taxonomy"] == V1 and reading["org_class"] == "parser-fix"
    pool = reading["pool"]
    parser = {sha(i) for i in range(200) if i % 7 != 6 and i % 2}
    assert pool and set(pool) <= parser
    assert all(split_of(ALPHA, c) == "confirmation" for c in pool)
    assert set(pool) == {c for c in parser if split_of(ALPHA, c) == "confirmation"}
    # the other class of the same parent is another cell with its own pool and budget
    r2 = env.post("/readings", json={**body, "org_class": "cli-fix"})
    assert r2.status_code == 201, r2.text
    assert not set(r2.json()["pool"]) & set(pool)


def test_the_sponsor_of_version_n_plus_one_cannot_sign_it(env: Env) -> None:
    _as(env, "approver")
    _propose(env, PARSER, CLI)
    entry = {
        "kind": "work-type", "slug": "lexer-fix", "title": "A fix to the lexer",
        "statement": "A change to how source text is split into tokens.", "parent_class": "bug.fix",
    }  # fmt: skip
    proposed = env.post(f"/library/{ALPHA}/entries", json=entry).json()
    _as(env, "admin")
    env.post(
        f"/library/{ALPHA}/entries/work-type/lexer-fix/sign", json={"version": proposed["version"]}
    )
    _as(env, "approver")
    v2 = env.post(
        f"/classes/{ORG}/versions/from-library",
        json={"repos": [ALPHA], "rules": {"lexer-fix": {"words": ["lexer"]}}},
    ).json()
    assert (v2["version_id"], v2["route"]["code"]) == ("acme/classes@v2", "class_set_unsigned")
    own = env.post(f"/classes/{ORG}/v/2/sign", json={"digest": v2["digest"]})
    assert own.status_code == 409 and envelope(own)["detail"]["code"] == "same_person"
    _as(env, "admin")
    other = env.post(f"/classes/{ORG}/v/2/sign", json={"digest": v2["digest"]})
    assert other.status_code == 200 and other.json()["status"] == "signed"


def test_a_reading_of_an_organisation_class_sits_on_its_parents_cell_and_counts_what_it_can_pool(
    env: Env,
) -> None:
    moved = [sha(i) for i in range(200) if i % 2 and i % 7 != 6][:40]  # parser commits
    with env.factory() as s:
        for t in s.execute(select(Task).where(Task.task_id.in_(moved))).scalars():
            t.capability_class = "docs.update"  # the miner read their paths as docs
        s.commit()
    v = _propose(env, PARSER, CLI, CHORE)
    _label_all(env)
    _as(env, "approver")
    env.post(f"/classes/{ORG}/v/1/sign", json={"digest": v["digest"]})
    _as(env, "operator")
    confirming = {c for c in moved if split_of(ALPHA, c) == "confirmation"}
    report = env.get(f"/classes/{ORG}/v/1").json()["report"]
    measurability = next(m for m in report["measures"] if m["name"] == "measurability")
    assert measurability["detail"]["other_parent"] >= len(confirming) > 0
    assert "mined under another global class" in measurability["words"]
    # the class page counts only what a reading of parser-fix can pool: its bug.fix commits
    page = env.get(f"/classes/{ORG}/v/1/classes/parser-fix").json()
    s_cell = next(x for x in page["sizes"] if x["size"] == "S")
    body = {
        "repo": ALPHA, "cell": CELL, "hierarchy": ["S3", S1], "posture_class": SEALED,
        "author_model": AUTHOR, "taxonomy": V1, "org_class": "parser-fix",
    }  # fmt: skip
    reading = env.post("/readings", json=body)
    assert reading.status_code == 201, reading.text
    assert s_cell["confirmation"] == len(reading.json()["pool"])
    assert not confirming & set(reading.json()["pool"])
    # a reading of parser-fix on another global class's cell is refused: it would be an
    # orphan cell no gate reads
    other = env.post(
        "/readings", json={**body, "cell": {**CELL, "capability_class": "docs.update"}}
    )
    assert other.status_code == 422 and "a child of bug.fix" in envelope(other)["message"]


def test_a_backlog_item_cannot_carry_an_organisations_class_by_hand(env: Env) -> None:
    routing = {
        "id": "I-9", "title": "Fix the parser", "capability_class": "bug.fix",
        "size_estimate": "S", "labels": {"taxonomy": V1, "org_class": "parser-fix"},
    }  # fmt: skip
    r = env.post(f"/factory/{ALPHA}/backlog", json={"items": [routing]})
    assert r.status_code == 422, r.text
    assert "written by an organisation's class set at intake" in str(r.json())
    fine = {**routing, "labels": {"team": "parser"}}
    assert env.post(f"/factory/{ALPHA}/backlog", json={"items": [fine]}).status_code == 201
    evo = env.post(
        f"/factory/{ALPHA}/backlog/evolutions",
        json={"item": {**routing, "id": "I-10", "labels": {"class_by": "rule"}}},
    )
    assert evo.status_code == 422


def test_one_organisations_class_sets_describe_a_repository(env: Env) -> None:
    _propose(env, PARSER, CLI, CHORE)
    r = env.post("/classes/aaa/versions", json={"repos": [ALPHA], "classes": [PARSER]})
    assert r.status_code == 409, r.text
    err = envelope(r)
    assert err["detail"]["code"] == "repository_has_a_class_set"
    assert "acme/classes@v1" in err["message"]
    assert env.get("/classes").json()["orgs"][0]["org"] == "acme"
    _as(env, "approver")
    env.post(f"/classes/{ORG}/v/1/revoke", json={"reason": "moving the repository to aaa"})
    _as(env, "operator")
    moved = env.post("/classes/aaa/versions", json={"repos": [ALPHA], "classes": [PARSER]})
    assert moved.status_code == 201, moved.text


def test_the_agreement_is_withheld_from_a_person_part_way_through_their_sample(env: Env) -> None:
    v = _propose(env, PARSER, CLI, CHORE)
    del v
    _as(env, "admin")
    queue = env.get(f"/classes/{ORG}/v/1/label-queue").json()["items"]

    def agreement() -> dict[str, Any]:
        report = env.get(f"/classes/{ORG}/v/1").json()["report"]
        return next(m for m in report["measures"] if m["name"] == "agreement")

    assert agreement()["state"] == "fail"  # nothing labelled yet: nothing of theirs to learn
    first = queue[0]
    env.post(
        f"/classes/{ORG}/v/1/labels",
        json={"repo": ALPHA, "task_id": first["task_id"], "class": "parser-fix"},
    )
    part = agreement()
    assert (part["state"], part["value"], part["detail"]) == ("withheld", None, {})
    assert f"you have labelled 1 of {len(queue)} commits" in part["words"]
    # another person still reads it
    _as(env, "viewer")
    assert agreement()["state"] == "fail" and agreement()["value"] is not None
    _as(env, "admin")
    rule = {"parser": "parser-fix", "parse": "parser-fix", "cli": "cli-fix", "flag": "cli-fix"}
    for item in queue[1:]:
        words = item["message"].replace("--", " ").split()
        klass = next((rule[w] for w in words if w in rule), "chore")
        env.post(
            f"/classes/{ORG}/v/1/labels",
            json={"repo": ALPHA, "task_id": item["task_id"], "class": klass},
        )
    done = agreement()
    assert done["state"] in ("pass", "fail") and done["value"] is not None


def test_the_index_lists_the_global_parents_and_a_refusal_names_its_class(env: Env) -> None:
    parents = env.get("/classes").json()["global_classes"]
    assert {"slug": "bug.fix", "definition": parents[[p["slug"] for p in parents].index(
        "bug.fix")]["definition"]} in parents  # fmt: skip
    assert "(unclassified)" not in {p["slug"] for p in parents}
    bad = {**CLI, "parent": "bugfix"}
    r = env.post(f"/classes/{ORG}/versions", json={"repos": [ALPHA], "classes": [PARSER, bad]})
    assert r.status_code == 422
    message = envelope(r)["message"]
    assert message.startswith("Class 2 (cli-fix): its parent 'bugfix' is not a global class")
    assert "bug.fix" in message and "feature.add" in message
    page = _propose(env, PARSER)
    assert page["version_id"] == V1
    assert env.get(f"/classes/{ORG}/v/1/classes/parser-fix").json()["parent_definition"]
