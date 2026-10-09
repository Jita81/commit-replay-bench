"""A fixture organisation's class set and the commits it describes — no real repository, no model.

The organisation ``acme`` splits the global ``bug.fix`` class in two by what its tickets say:
``parser-fix`` (the text names the parser) and ``cli-fix`` (the text names the command line).
``commits(n)`` gives ``n`` commit ids and messages that alternate between the two, with a
third kind every seventh commit that neither class names. ``version()`` is the set as its
sponsor proposes it; ``cases()`` the report's view of the commits.

Navigation
----------
What it is:   Shared fixture data for the class-set tests: the organisation, its two classes,
              their rules, a list of synthetic commits and helpers that build the version, the
              cases and a person-labelled sample.
What it does: Gives each test the same deterministic organisation, so the split, the report's
              numbers and the relabel are reproducible; the commit ids are sha1 of a counter so
              the split is fixed.
How:          Plain functions over ``crb.core.class_sets``; ``add_commits`` alone writes, as
              ``Task`` rows of a test store.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9)
Works with:   tests/test_class_sets.py (the core over it), tests/test_server_routes_classes.py
              and tests/test_class_set_hooks.py (seed the store from it),
              src/crb/core/class_sets.py (the record it builds)
Tested by:    tests/test_class_sets.py
Touch when:   never for a new repository; a class-set test needs another shape of commit — keep
              the counts the tests assert.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from crb.core.class_sets import (
    Case,
    ClassRule,
    ClassSetVersion,
    OrgClass,
    PersonLabel,
    classify,
    example_keys,
    from_message,
)
from crb.core.spec import TaskSpec
from crb.store.models import Task

ORG = "acme"
REPO = "alpha"
SPONSOR = "a" * 32
APPROVER = "b" * 32
LABELLER = "c" * 32

PARSER = OrgClass(
    slug="parser-fix",
    title="A fix to the parser",
    definition="A change that corrects how the parser reads its input; the ticket names the parser.",
    parent="bug.fix",
    rule=ClassRule(words=("parser", "parse")),
)
CLI = OrgClass(
    slug="cli-fix",
    title="A fix to the command line",
    definition="A change that corrects the command line's flags or output; the ticket names the CLI.",
    parent="bug.fix",
    rule=ClassRule(words=("cli", "flag")),
)


def sha(i: int) -> str:
    return hashlib.sha1(f"acme-commit-{i}".encode()).hexdigest()


def message(i: int) -> str:
    if i % 7 == 6:
        return f"chore: bump the version to {i}"
    return (
        f"fix: the parser drops a token ({i})" if i % 2 else f"fix: the cli flag --x{i} is ignored"
    )


def version(
    n: int = 1, *, sponsor: str = SPONSOR, repos: tuple[str, ...] = (REPO,)
) -> ClassSetVersion:
    return ClassSetVersion(org=ORG, n=n, classes=(PARSER, CLI), repos=repos, proposed_by=sponsor)


def cases(count: int = 200, *, size: str = "S", repo: str = REPO) -> list[Case]:
    """The report's view of ``count`` commits, each mined as ``bug.fix`` (as
    :func:`add_commits` writes them)."""
    v = version()
    return [
        Case(
            repo=repo,
            task_id=sha(i),
            split=v.split(repo, sha(i)),
            size=size,
            message=from_message(message(i)),
            mined_class="bug.fix",
        )
        for i in range(count)
    ]


def agreeing_labels(cs: list[Case], *, labeller: str = LABELLER) -> list[PersonLabel]:
    """A person who reads every derivation commit they are offered exactly as the rule does
    (a class's example commits are never offered)."""
    v = version()
    shown = example_keys(cs)
    return [
        PersonLabel(c.repo, c.task_id, classify(v, c.fields).slug, labeller)
        for c in cs
        if c.split == "derivation" and (c.repo, c.task_id) not in shown
    ]


def add_commits(factory: sessionmaker[Session], n: int = 200, *, repo: str = REPO) -> list[str]:
    """The organisation's commits as mined tasks of ``repo``: bug.fix, size S, python,
    qualified, each its own change."""
    ids = [sha(i) for i in range(n)]
    with factory() as s:
        for i, tid in enumerate(ids):
            spec = TaskSpec(
                task_id=tid,
                repo=repo,
                subject=message(i),
                authored="2026-08-01T12:00:00+00:00",
                test_files=(f"tests/test_c{i}.py",),
                src_files=(f"src/pkg/c{i}.py",),
                target_tests=(f"tests/test_c{i}.py",),
                belt_scope=("tests/",),
                size="S",
                src_churn=12,
                capability_class="bug.fix",
                language="python",
                red_checked=True,
                gold_clean=True,
                labels={"change_id": f"change-acme-{i}"},
            )
            s.add(
                Task(
                    repo=repo,
                    task_id=tid,
                    pool=spec.pool,
                    size="S",
                    capability_class="bug.fix",
                    language="python",
                    authored=spec.authored,
                    subject=spec.subject,
                    red_checked=True,
                    gold_clean=True,
                    spec_json=spec.to_dict(),
                )
            )
        s.commit()
    return ids


#: The classes as ``POST /classes/{org}/versions`` takes them; ``CHORE_IN`` names the fixture
#: organisation's chores and the seed's own ``fix: task <n>`` commits, so coverage passes.
PARSER_IN = {
    "slug": PARSER.slug,
    "title": PARSER.title,
    "definition": PARSER.definition,
    "parent": PARSER.parent,
    "rule": {"words": list(PARSER.rule.words)},
}
CLI_IN = {
    "slug": CLI.slug,
    "title": CLI.title,
    "definition": CLI.definition,
    "parent": CLI.parent,
    "rule": {"words": list(CLI.rule.words)},
}
CHORE_IN = {
    "slug": "chore",
    "title": "Housekeeping",
    "definition": "Version bumps, fixes of the seed's own tasks and other housekeeping.",
    "parent": "docs.update",
    "rule": {"words": ["chore", "task"]},
}


def label_all(env: Any, n: int = 1) -> int:
    """As the signed-in person (never the version's sponsor), label every derivation commit
    ``acme`` version ``n`` offers the way the rule reads it (a person who agrees with the rule)."""
    queue = env.get(f"/classes/{ORG}/v/{n}/label-queue").json()
    assert queue["sponsor"] is False, "the sponsor is offered nothing to label"
    words = {"parser": "parser-fix", "parse": "parser-fix", "cli": "cli-fix", "flag": "cli-fix"}
    done = 0
    for item in queue["items"]:
        said = item["message"].replace("--", " ").split()
        klass = next((words[w] for w in said if w in words), "chore")
        r = env.post(
            f"/classes/{ORG}/v/{n}/labels",
            json={"repo": item["repo"], "task_id": item["task_id"], "class": klass},
        )
        assert r.status_code == 201, r.text
        done += 1
    return done


def routing_version(env: Any) -> dict[str, Any]:
    """``acme/classes@v1`` over ``alpha``, proposed by the operator (its sponsor), labelled in
    full by the admin and signed by the approver — three people: a version that routes. Leaves
    the operator signed in."""
    from fixtures.server_seed import login, logout

    r = env.post(
        f"/classes/{ORG}/versions", json={"repos": [REPO], "classes": [PARSER_IN, CLI_IN, CHORE_IN]}
    )
    assert r.status_code == 201, r.text
    proposed = dict(r.json())
    logout(env.client)
    login(env.client, "admin")
    label_all(env)
    logout(env.client)
    login(env.client, "approver")
    signed = env.post(f"/classes/{ORG}/v/1/sign", json={"digest": proposed["digest"]}).json()
    assert signed["route"]["routes"] is True, signed
    logout(env.client)
    login(env.client, "operator")
    return dict(signed)


def seed_routing_version(factory: sessionmaker[Session], *, repo: str = REPO) -> str:
    """Write a routing ``acme/classes@v1`` over ``repo`` straight into the store — proposed by
    :data:`SPONSOR` with the chores class, labelled in full by :data:`LABELLER` as the rule
    reads it, signed by :data:`APPROVER` — for a test that has a store but no app (the worker).
    ``repo`` must already hold :func:`add_commits`'s commits. Returns the version id."""
    from crb.core.class_sets import ACT_PROPOSE, ACT_SIGN
    from crb.server.class_set_state import cases_for
    from crb.store.class_sets import SOURCE_PERSON, DbClassSets, new_act

    chores = OrgClass(
        slug="chore", title="Housekeeping", definition="Version bumps and other housekeeping.",
        parent="docs.update", rule=ClassRule(words=("chore", "task")),
    )  # fmt: skip
    v = ClassSetVersion(
        org=ORG, n=1, classes=(PARSER, CLI, chores), repos=(repo,), proposed_by=SPONSOR
    )
    store = DbClassSets(factory)
    store.append(new_act(ORG, v.version_id, v.digest, ACT_PROPOSE, SPONSOR,
                         body={"version": v.content()}))  # fmt: skip
    with factory() as s:
        cs = cases_for(s, v)
    shown = example_keys(cs)
    store.add_labels(
        v.version_id,
        [(c.repo, c.task_id, classify(v, c.fields).slug) for c in cs
         if c.split == "derivation" and (c.repo, c.task_id) not in shown],
        source=SOURCE_PERSON, labeller=LABELLER,
    )  # fmt: skip
    store.append(new_act(ORG, v.version_id, v.digest, ACT_SIGN, APPROVER))
    return v.version_id
