"""An organisation's class sets, in the core: the split, the one rule, the acts, the report.

Navigation
----------
What it is:   Unit tests of ``crb.core.class_sets`` over the fixture organisation ``acme``.
What it does: Pins that the split is the seeded hash ADR-0026 item 9 names, fixed per commit
              and about one third derivation; that a rule reads only ticket-time fields (no
              path, line count or churn can be an input); that the one classifier honours a
              person's ``crb:class=`` override, then the first matching class, else unclassified;
              that a version is its organisation's next number, signed only by a person who is
              not its sponsor through the library's one two-person rule, with the digest they
              read; that the validity report computes coverage, κ against a person's labels on
              derivation commits only, stability, ticket consistency, size agreement,
              measurability and the override rate against ADR-0026's thresholds, each routing
              clause failing the version on its own; that the per-class minimum counts
              labelled commits; that the sponsor's labels and a class's example commits are
              never read; that measurability counts only commits mined under the class's
              parent; that the route verdict names only the checks that stop routing; that a
              version routes only when signed and passing; and that a reading's pool refuses a
              derivation commit, a version that does not route and a registration made before
              the signature.
How:          Plain calls over ``tests/fixtures/class_sets.py``; no store.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9)
Works with:   src/crb/core/class_sets.py (under test), tests/fixtures/class_sets.py (the
              organisation), src/crb/core/library.py (the one two-person rule)
Tested by:    this file
Touch when:   never for a new repository; a threshold, a measure or an act of a class set
              changes (ADR-0026 item 9 first).
"""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from crb.core import class_sets as cs
from crb.core import library
from crb.core.ledger import LedgerIntegrityError
from crb.core.reading import ReadingRefused
from crb.core.taxonomy import UNCLASSIFIED
from fixtures.class_sets import (
    APPROVER,
    CLI,
    ORG,
    PARSER,
    REPO,
    SPONSOR,
    agreeing_labels,
    cases,
    sha,
    version,
)


def _tier(points: float) -> str:
    return "XS" if points <= 1 else "S" if points <= 3 else "M" if points <= 8 else "L"


def _act(act: str, v: cs.ClassSetVersion, actor: str, **body: object) -> cs.ClassSetAct:
    return cs.ClassSetAct(
        act_id=hashlib.sha1(f"{act}{actor}{body}".encode()).hexdigest()[:32],
        org=v.org,
        version_id=v.version_id,
        digest=str(body.pop("digest", v.digest)),
        act=act,
        actor=actor,
        created=str(body.pop("created", "2026-09-28T10:00:00+00:00")),
        body={"version": v.content()} if act == cs.ACT_PROPOSE else dict(body),
    )


# --- the split -------------------------------------------------------------------------


def test_the_split_is_the_seeded_hash_per_commit_and_about_one_third_derivation() -> None:
    commit = sha(1)
    digest = hashlib.sha256(f"crb.split.v1|{REPO}|{commit}".encode()).hexdigest()
    expect = "derivation" if int(digest[:16], 16) / 16**16 < 1 / 3 else "confirmation"
    assert cs.split_of(REPO, commit) == expect
    assert pytest.approx(1 / 3) == cs.DERIVATION_SHARE  # ADR-0026 item 9: one third, fixed (DL-371)
    splits = [cs.split_of(REPO, sha(i)) for i in range(3000)]
    share = splits.count("derivation") / len(splits)
    assert 0.30 < share < 0.37  # a binomial of 3000 at 1/3 lies here with overwhelming odds
    # the same commit in another repository is split on its own
    assert {cs.split_of("beta", sha(i)) == cs.split_of(REPO, sha(i)) for i in range(50)} == {
        True,
        False,
    }
    # the version records its share and seed, and splits by them
    v = version()
    assert v.content()["derivation_share"] == pytest.approx(1 / 3)
    assert v.content()["split_seed"] == "crb.split.v1"
    assert v.split(REPO, commit) == expect


# --- the one rule ------------------------------------------------------------------------


def test_a_rule_reads_only_ticket_time_fields() -> None:
    assert cs.TICKET_TIME_FIELDS == (
        "text",
        "work_item_type",
        "component",
        "labels",
        "points",
        "source",
    )
    for forbidden in ("paths", "changed_paths", "churn", "lines", "diff", "files"):
        assert forbidden not in {f.name for f in dataclasses.fields(cs.TicketFields)}
        assert forbidden not in {f.name for f in dataclasses.fields(cs.ClassRule)}
    with pytest.raises(ValueError, match="at least one"):
        cs.ClassRule()
    with pytest.raises(ValueError, match="override"):
        cs.ClassRule(labels=("crb:class=parser-fix",))


def test_the_classifier_honours_an_override_then_the_first_matching_class_then_none() -> None:
    v = version()
    t = cs.TicketFields(text="The parser rejects the cli flag", source="ticket@2026-09-01")
    assert cs.classify(v, t).slug == "parser-fix"  # first class in priority order
    over = dataclasses.replace(t, labels=("crb:class=cli-fix",))
    d = cs.classify(v, over)
    assert (d.slug, d.parent, d.by, d.proxy) == ("cli-fix", "bug.fix", "override", False)
    unknown = dataclasses.replace(t, labels=("crb:class=nothing",))
    assert cs.classify(v, unknown).by == "rule"
    none = cs.classify(v, cs.from_message("chore: bump the version"))
    assert (none.slug, none.by, none.proxy) == (UNCLASSIFIED, "none", True)
    # words are whole words: "parsers" is not "parser", "clip" is not "cli"
    assert cs.classify(v, cs.from_message("clip the parsers")).slug == UNCLASSIFIED


def test_a_component_is_the_ticket_area_or_a_name_in_its_text() -> None:
    rule = cs.ClassRule(components=("billing",), work_item_types=("bug",))
    assert rule.matches(
        cs.TicketFields(text="x", work_item_type="Bug", component="Billing", source="ticket@d")
    )
    assert rule.matches(
        cs.TicketFields(text="the billing page", work_item_type="bug", source="ticket@d")
    )
    assert not rule.matches(
        cs.TicketFields(text="the billing page", work_item_type="story", source="ticket@d")
    )


def test_an_organisation_class_is_a_child_of_a_global_class_and_named_apart() -> None:
    with pytest.raises(ValueError, match="global class"):
        dataclasses.replace(PARSER, slug="bug.fix")
    with pytest.raises(ValueError, match="parent"):
        dataclasses.replace(PARSER, parent="made.up")
    with pytest.raises(ValueError, match="global"):
        cs.ClassSetVersion(org="global", n=1, classes=(PARSER,), repos=(REPO,), proposed_by=SPONSOR)
    with pytest.raises(ValueError, match="person"):
        cs.ClassSetVersion(org=ORG, n=1, classes=(PARSER,), repos=(REPO,), proposed_by="mined:x@1")
    assert version().version_id == "acme/classes@v1"


# --- the acts and the two-person rule ------------------------------------------------------


def test_a_version_is_signed_only_by_a_second_person_through_the_library_rule() -> None:
    assert cs.refuse_same_person is library.refuse_same_person  # one rule, never a copy
    v = version()
    states: dict[str, cs.VersionState] = {}
    states[v.version_id] = cs.apply(states, _act(cs.ACT_PROPOSE, v, SPONSOR))
    assert states[v.version_id].status == "proposed" and states[v.version_id].sponsor == SPONSOR
    with pytest.raises(library.LibraryRefused) as own:  # the library's own refusal
        cs.apply(states, _act(cs.ACT_SIGN, v, SPONSOR))
    assert own.value.code == "same_person" and "second person" in str(own.value)
    with pytest.raises(cs.ClassSetRefused) as miner:
        cs.apply(states, _act(cs.ACT_SIGN, v, "mined:classes@1"))
    assert miner.value.code == "not_a_person"
    with pytest.raises(cs.ClassSetRefused) as stale:
        cs.apply(states, _act(cs.ACT_SIGN, v, APPROVER, digest="0" * 64))
    assert stale.value.code == "version_mismatch"
    signed = cs.apply(states, _act(cs.ACT_SIGN, v, APPROVER))
    assert (signed.status, signed.approver) == ("signed", APPROVER)


def test_a_version_is_the_organisations_next_number_and_never_proposed_twice() -> None:
    v1 = version()
    states = {v1.version_id: cs.apply({}, _act(cs.ACT_PROPOSE, v1, SPONSOR))}
    for n in (1, 3):
        with pytest.raises(cs.ClassSetRefused) as e:
            cs.apply(states, _act(cs.ACT_PROPOSE, version(n), SPONSOR))
        assert e.value.code == "version_out_of_order"
    v2 = cs.apply(states, _act(cs.ACT_PROPOSE, version(2), SPONSOR))
    assert v2.version_id == "acme/classes@v2"


def test_a_revocation_says_why_and_the_chain_verifies() -> None:
    v = version()
    acts = [_act(cs.ACT_PROPOSE, v, SPONSOR), _act(cs.ACT_SIGN, v, APPROVER)]
    states = cs.fold(acts)
    with pytest.raises(cs.ClassSetRefused) as e:
        cs.apply(states, _act(cs.ACT_REVOKE, v, APPROVER, reason=" "))
    assert e.value.code == "reason_missing"
    revoked = cs.apply(states, _act(cs.ACT_REVOKE, v, APPROVER, reason="the parser was split"))
    assert revoked.status == "revoked"
    prev = "0" * 64
    chained = []
    for a in acts:
        a = a.chained(prev)
        prev = a.row_hash
        chained.append(a)
    assert cs.verify_chain(chained) == 2
    tampered = [chained[0], dataclasses.replace(chained[1], actor=SPONSOR)]
    with pytest.raises(LedgerIntegrityError):
        cs.verify_chain(tampered)
    # a fold over a stored act the rule would now refuse is an integrity error, never skipped
    with pytest.raises(LedgerIntegrityError):
        cs.fold([_act(cs.ACT_PROPOSE, v, SPONSOR), _act(cs.ACT_SIGN, v, SPONSOR)])


# --- the validity report -------------------------------------------------------------------


def test_cohen_kappa() -> None:
    assert cs.cohen_kappa([]) is None
    assert cs.cohen_kappa([("a", "a"), ("b", "b")]) == pytest.approx(1.0)
    # 50 pairs: 20 a/a, 15 b/b, 5 a/b, 10 b/a → po 0.7, pe 0.5·0.6+0.5·0.4 = 0.5, κ 0.4
    pairs = [("a", "a")] * 20 + [("b", "b")] * 15 + [("a", "b")] * 5 + [("b", "a")] * 10
    assert cs.cohen_kappa(pairs) == pytest.approx(0.4)


def test_a_report_with_an_agreeing_sample_and_enough_confirmation_commits_passes() -> None:
    commits = cases(200)
    report = cs.validity_report(version(), commits, agreeing_labels(commits), points_tier=_tier)
    by = {m.name: m for m in report.measures}
    # 1 in 7 commits is a chore no class names: coverage is 172 of 200 (86%), below 90%
    assert by["coverage"].state == "fail" and by["coverage"].value == pytest.approx(172 / 200)
    assert not report.passes
    assert by["agreement"].value == pytest.approx(1.0) and by["agreement"].state == "pass"
    assert by["stability"].value == pytest.approx(1.0)
    assert by["ticket_consistency"].state == "not_applicable"  # no linked ticket at all
    assert by["size_agreement"].state == "fail" and not report.size_from_points
    assert by["measurability"].state == "pass"
    assert set(report.routable_cells) == {("parser-fix", "S"), ("cli-fix", "S")}
    assert by["override_rate"].value == pytest.approx(0.0)
    assert report.derivation + report.confirmation == 200
    # a class that also names the chores covers everything, and then the report passes
    chores = cs.OrgClass(
        slug="chore", title="Chores", definition="Version bumps and housekeeping.",
        parent="docs.update", rule=cs.ClassRule(words=("chore",)),
    )  # fmt: skip
    wide = dataclasses.replace(version(), classes=(PARSER, CLI, chores))
    passing = cs.validity_report(wide, commits, _labels(wide, commits), points_tier=_tier)
    assert passing.passes, [m.to_dict() for m in passing.measures if not m.passed]


def _labels(v: cs.ClassSetVersion, commits: list[cs.Case]) -> list[cs.PersonLabel]:
    return [
        cs.PersonLabel(c.repo, c.task_id, cs.classify(v, c.fields).slug, "c" * 32)
        for c in commits
        if c.split == "derivation"
    ]


def test_agreement_reads_derivation_commits_only_and_needs_the_sample_and_five_per_class() -> None:
    commits = cases(200)
    v = version()
    # a person who labels only confirmation commits gives no sample at all
    confirming = [
        cs.PersonLabel(c.repo, c.task_id, cs.classify(v, c.fields).slug, "c" * 32)
        for c in commits
        if c.split == "confirmation"
    ]
    agreement = cs.validity_report(v, commits, confirming, points_tier=_tier).measure("agreement")
    assert agreement.n == 0 and agreement.state == "fail"
    # a sample under 50 commits fails however well it agrees
    few = agreeing_labels(commits)[:30]
    agreement = cs.validity_report(v, commits, few, points_tier=_tier).measure("agreement")
    assert agreement.n == 30 and agreement.state == "fail" and "20 more" in agreement.words
    # a person who disagrees on every cli commit drives κ below 0.6
    wrong = [
        dataclasses.replace(lab, slug="parser-fix") if lab.slug == "cli-fix" else lab
        for lab in agreeing_labels(commits)
    ]
    agreement = cs.validity_report(v, commits, wrong, points_tier=_tier).measure("agreement")
    assert agreement.value is not None and agreement.value < cs.KAPPA_MIN
    assert "fewer than 5 labelled commits in cli-fix" in agreement.words


def test_ticket_consistency_size_agreement_and_the_override_rate() -> None:
    v = version()
    commits = []
    for c in cases(60):
        # a linked ticket that says what the message says, pointed to the churn tier (S = 2)
        ticket = cs.TicketFields(text=c.message.text, points=2.0, source="ticket@2026-08-01")
        commits.append(dataclasses.replace(c, ticket=ticket))
    report = cs.validity_report(v, commits, [], points_tier=_tier)
    assert report.measure("ticket_consistency").state == "pass"
    assert report.measure("size_agreement").state == "pass" and report.size_from_points
    # points that name a smaller tier than the change fail it
    small = [
        dataclasses.replace(c, ticket=dataclasses.replace(c.ticket, points=1.0)) for c in commits
    ]  # type: ignore[arg-type]
    assert (
        cs.validity_report(v, small, [], points_tier=_tier).measure("size_agreement").state
        == "fail"
    )
    # a person's override on a third of the tickets is too many
    over = [
        dataclasses.replace(c, ticket=dataclasses.replace(c.ticket, labels=("crb:class=cli-fix",)))  # type: ignore[arg-type]
        if i % 3 == 0
        else c
        for i, c in enumerate(commits)
    ]
    rate = cs.validity_report(v, over, [], points_tier=_tier).measure("override_rate")
    assert rate.state == "fail" and rate.value is not None and rate.value > cs.OVERRIDE_RATE_MAX
    # the intake's overrides count too
    rate = cs.validity_report(
        v, commits, [], points_tier=_tier, intake_overrides=30, intake_classified=30
    ).measure("override_rate")
    assert rate.state == "fail"


# --- routing and the reading's pool ------------------------------------------------------


def _signed(v: cs.ClassSetVersion) -> cs.VersionState:
    return cs.VersionState(
        version=v, status="signed", sponsor=SPONSOR, proposed_at="2026-09-28T09:00:00+00:00",
        approver=APPROVER, signed_at="2026-09-28T10:00:00+00:00",
    )  # fmt: skip


def test_a_version_routes_only_when_signed_by_a_second_person_and_its_report_passes() -> None:
    chores = cs.OrgClass(
        slug="chore", title="Chores", definition="Housekeeping.", parent="docs.update",
        rule=cs.ClassRule(words=("chore",)),
    )  # fmt: skip
    v = dataclasses.replace(version(), classes=(PARSER, CLI, chores))
    commits = cases(200)
    good = cs.validity_report(v, commits, _labels(v, commits), points_tier=_tier)
    failing = cs.validity_report(v, commits, [], points_tier=_tier)
    unsigned = dataclasses.replace(_signed(v), status="proposed", approver="", signed_at="")
    assert cs.routes(None, good).code == "class_set_unknown"
    assert cs.routes(unsigned, good).code == "class_set_unsigned"
    assert (
        cs.routes(dataclasses.replace(_signed(v), status="revoked"), good).code
        == "class_set_revoked"
    )
    verdict = cs.routes(_signed(v), failing)
    assert (verdict.ok, verdict.code) == (False, "class_set_report_failed")
    assert "agreement" in verdict.words
    assert cs.routes(_signed(v), good).ok


def test_a_reading_pool_holds_confirmation_commits_of_a_routing_version_after_its_signature() -> (
    None
):
    chores = cs.OrgClass(
        slug="chore", title="Chores", definition="Housekeeping.", parent="docs.update",
        rule=cs.ClassRule(words=("chore",)),
    )  # fmt: skip
    v = dataclasses.replace(version(), classes=(PARSER, CLI, chores))
    commits = cases(200)
    good = cs.validity_report(v, commits, _labels(v, commits), points_tier=_tier)
    state = _signed(v)
    confirming = [c.task_id for c in commits if c.split == "confirmation"]
    deriving = [c.task_id for c in commits if c.split == "derivation"]
    later = "2026-09-29T00:00:00+00:00"
    cs.refuse_reading_pool(
        state, good, repo=REPO, org_class="parser-fix", pool=confirming, now=later
    )
    with pytest.raises(ReadingRefused) as e:
        cs.refuse_reading_pool(
            state,
            good,
            repo=REPO,
            org_class="parser-fix",
            pool=confirming + deriving[:1],
            now=later,
        )
    assert e.value.code == "derivation_commit" and e.value.detail["n"] == 1
    with pytest.raises(ReadingRefused) as before:
        cs.refuse_reading_pool(
            state,
            good,
            repo=REPO,
            org_class="parser-fix",
            pool=confirming,
            now="2026-09-28T09:30:00+00:00",
        )
    assert before.value.code == "class_set_not_routing"
    unsigned = dataclasses.replace(state, status="proposed", signed_at="")
    with pytest.raises(ReadingRefused) as not_routing:
        cs.refuse_reading_pool(
            unsigned, good, repo=REPO, org_class="parser-fix", pool=confirming, now=later
        )
    assert not_routing.value.detail["route"] == "class_set_unsigned"
    with pytest.raises(ReadingRefused):
        cs.refuse_reading_pool(
            state, good, repo="beta", org_class="parser-fix", pool=confirming, now=later
        )
    with pytest.raises(ReadingRefused):
        cs.refuse_reading_pool(
            state, good, repo=REPO, org_class="nothing", pool=confirming, now=later
        )


def test_the_fixture_org_is_what_the_tests_assume() -> None:
    assert ORG == "acme" and CLI.parent == PARSER.parent == "bug.fix"


# --- each clause of the report, alone (P-689) ---------------------------------------------


def _wide() -> cs.ClassSetVersion:
    chores = cs.OrgClass(
        slug="chore", title="Chores", definition="Housekeeping.", parent="docs.update",
        rule=cs.ClassRule(words=("chore",)),
    )  # fmt: skip
    return dataclasses.replace(version(), classes=(PARSER, CLI, chores))


def _only_failing(report: cs.ValidityReport) -> list[str]:
    return [m.name for m in report.measures if m.state == "fail" and m.name != "size_agreement"]


def test_the_per_class_minimum_counts_labelled_commits_not_labels() -> None:
    lexer = cs.OrgClass(
        slug="lexer-fix", title="Lexer", definition="A fix to the lexer.", parent="bug.fix",
        rule=cs.ClassRule(words=("lexer",)),
    )  # fmt: skip
    v = dataclasses.replace(_wide(), classes=(*_wide().classes, lexer))
    ids = [f"{i:040x}" for i in range(40) if not cs.set_aside(REPO, f"{i:040x}")][:3]
    lexers = [
        cs.Case(REPO, t, "derivation", "S", cs.from_message(f"fix: the lexer {t[-4:]}"),
                mined_class="bug.fix")
        for t in ids
    ]  # fmt: skip
    commits = cases(200) + lexers
    labels = _labels(v, commits)
    # three lexer commits, each labelled by two people: six labels, three commits — under the
    # five a class needs
    labels += [cs.PersonLabel(c.repo, c.task_id, "lexer-fix", "d" * 32) for c in lexers]
    report = cs.validity_report(v, commits, labels, points_tier=_tier)
    agreement = report.measure("agreement")
    assert agreement.value is not None and agreement.value >= cs.KAPPA_MIN
    assert agreement.n >= cs.SAMPLE_MIN
    assert agreement.detail["per_class"]["lexer-fix"] == 3
    assert (
        agreement.state == "fail"
        and "fewer than 5 labelled commits in lexer-fix" in agreement.words
    )
    assert _only_failing(report) == ["agreement"]
    verdict = cs.routes(_signed(v), report)
    assert (verdict.code, "agreement" in verdict.words) == ("class_set_report_failed", True)


def test_ticket_consistency_alone_stops_the_version() -> None:
    v = _wide()
    commits = []
    for i, c in enumerate(cases(200)):
        # a quarter of the parser tickets say "cli" where the message says "parser"
        said = "fix: the cli flag is ignored" if (i % 4 == 1 and i % 7 != 6) else c.message.text
        commits.append(
            dataclasses.replace(c, ticket=cs.TicketFields(text=said, source="ticket@2026-08-01"))
        )
    report = cs.validity_report(v, commits, _labels(v, commits), points_tier=_tier)
    consistency = report.measure("ticket_consistency")
    assert consistency.state == "fail" and consistency.value == pytest.approx(0.785)
    assert _only_failing(report) == ["ticket_consistency"]
    verdict = cs.routes(_signed(v), report)
    assert verdict.code == "class_set_report_failed" and "(ticket consistency)" in verdict.words


def test_measurability_alone_stops_the_version_and_reads_confirmation_commits_only() -> None:
    v = _wide()
    sizes = ("XS", "S", "M", "L", "XL")
    spread = [dataclasses.replace(c, size=sizes[i % 5]) for i, c in enumerate(cases(200))]
    report = cs.validity_report(v, spread, _labels(v, spread), points_tier=_tier)
    assert report.measure("measurability").state == "fail" and not report.routable_cells
    assert _only_failing(report) == ["measurability"]
    assert "(measurability)" in cs.routes(_signed(v), report).words
    # thirty derivation commits and ten confirmation commits in one cell: only the ten count
    few = [
        cs.Case(REPO, f"{i:040x}", "derivation" if i < 30 else "confirmation", "S",
                cs.from_message("fix: the parser"), mined_class="bug.fix")
        for i in range(40)
    ]  # fmt: skip
    measure = cs.validity_report(v, few, [], points_tier=_tier).measure("measurability")
    assert measure.state == "fail" and measure.detail["cells"] == [
        {"class": "parser-fix", "size": "S", "n": 10}
    ]


def test_measurability_counts_only_commits_a_reading_of_the_class_can_pool() -> None:
    v = _wide()
    # thirty confirmation commits the rule puts in parser-fix, mined under docs.update: a
    # reading of parser-fix sits on bug.fix's cell and can never pool them
    elsewhere = [
        cs.Case(REPO, f"{i:040x}", "confirmation", "S", cs.from_message("fix: the parser"),
                mined_class="docs.update")
        for i in range(30)
    ]  # fmt: skip
    measure = cs.validity_report(v, elsewhere, [], points_tier=_tier).measure("measurability")
    assert measure.state == "fail" and measure.detail["other_parent"] == 30
    assert "30 more qualified confirmation commits of these classes were mined under another" in (
        measure.words
    )
    home = [dataclasses.replace(c, mined_class="bug.fix") for c in elsewhere]
    assert cs.validity_report(v, home, [], points_tier=_tier).routable_cells == (
        ("parser-fix", "S"),
    )


def test_points_naming_a_smaller_tier_too_often_fail_size_agreement_which_never_stops_routing() -> (
    None
):
    v = _wide()
    commits = []
    for i, c in enumerate(cases(60)):
        # 50 tickets pointed to the churn tier (S), 10 to a smaller one (XS): 83% agree, 17% small
        points = 1.0 if i < 10 else 2.0
        ticket = cs.TicketFields(text=c.message.text, points=points, source="ticket@2026-08-01")
        commits.append(dataclasses.replace(c, ticket=ticket))
    size = cs.validity_report(v, commits, [], points_tier=_tier).measure("size_agreement")
    assert size.value is not None and size.value >= cs.SIZE_EQUAL_MIN
    assert size.state == "fail" and "a smaller tier for 10" in size.words
    # the route verdict names only the checks that stop routing, never the points check
    many = cases(200)
    failing = cs.validity_report(v, many, [], points_tier=_tier)
    assert failing.measure("size_agreement").state == "fail"
    verdict = cs.routes(_signed(v), failing)
    assert "agreement" in verdict.words and "size agreement" not in verdict.words
    passing = cs.validity_report(v, many, _labels(v, many), points_tier=_tier)
    assert passing.measure("size_agreement").state == "fail" and passing.passes
    assert cs.routes(_signed(v), passing).ok


def test_the_sponsors_labels_and_example_commits_are_never_read() -> None:
    v = _wide()
    commits = cases(200)
    by_sponsor = [dataclasses.replace(x, labeller=SPONSOR) for x in _labels(v, commits)]
    agreement = cs.validity_report(v, commits, by_sponsor, points_tier=_tier).measure("agreement")
    assert agreement.n == 0 and agreement.state == "fail"
    assert agreement.detail["set_aside"]["sponsor"] == len(by_sponsor)
    assert "of the sponsor's own labels are not read" in agreement.words
    # the set-aside commits are derivation commits drawn per commit; the page's examples are some
    shown = cs.example_keys(commits)
    assert shown and all(c.split == "derivation" for c in commits if (c.repo, c.task_id) in shown)
    examples = cs.examples_of(v, commits)
    assert any(examples.values())
    assert all(
        len(examples[k.slug]) <= cs.EXAMPLES_PER_CLASS
        and all((c.repo, c.task_id) in shown for c in examples[k.slug])
        and all(cs.classify(v, c.fields).slug == k.slug for c in examples[k.slug])
        for k in v.classes
    )
    # mining more history never moves a commit into or out of the set-aside draw
    assert shown <= cs.example_keys(cases(400))
    only_shown = [x for x in _labels(v, commits) if (x.repo, x.task_id) in shown]
    agreement = cs.validity_report(v, commits, only_shown, points_tier=_tier).measure("agreement")
    assert agreement.n == 0 and agreement.detail["set_aside"]["examples"] == len(only_shown)


def test_a_parent_that_is_not_a_global_class_is_refused_with_the_ones_that_are() -> None:
    with pytest.raises(ValueError) as e:
        dataclasses.replace(PARSER, parent="bugfix")
    assert "'bugfix' is not a global class" in str(e.value)
    assert all(p in str(e.value) for p in ("bug.fix", "feature.add", "refactor"))
    assert UNCLASSIFIED not in cs.global_parents()
