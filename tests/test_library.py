"""The context library's record, its two-person rule and its page per work type (ADR-0026 item 10).

Navigation
----------
What it is:   Unit tests of ``crb.core.library`` — the entry record, the acts and their chain,
              the fold into a status, staleness, the page per work type — and the guard that
              no entry reaches a builder's brief.
What it does: Pins the six kinds and the ``<kind>/<slug>`` id, the 400-character statement,
              provenance, a standard's ISO/IEC 25010 characteristic and its check (advisory
              without one), the sponsor-and-approver rule (the approver is never the sponsor;
              a miner or a model is never a person), revocation and retirement by appending,
              staleness when the source file changes, a tampered chain, and that nothing that
              composes a brief can import the library.
How:          Pure core calls over constructed entries and acts; the brief guard reads
              ``pyproject.toml``'s import-linter contract and walks the brief composers' ASTs.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 10)
Works with:   src/crb/core/library.py (the record, the rule and the page under test),
              pyproject.toml (the contract "library entries never reach a brief"),
              src/crb/builders/base.py (``BuildBrief`` — no field an entry could reach),
              tests/test_worker.py (a replay's briefs carry no signed entry's words)
Tested by:    this file
Touch when:   never for a new repository; the record, a kind, an act or the rule changes in
              ADR-0026 item 10 first.
"""

from __future__ import annotations

import ast
import importlib
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
from crb.core.library import (
    ACT_PROPOSE,
    ACT_RETIRE,
    ACT_REVOKE,
    ACT_SIGN,
    ACT_SPONSOR,
    ACT_STALE,
    ACTOR_MEASUREMENT,
    ISO_25010_CHARACTERISTICS,
    KINDS,
    STATUS_PROPOSED,
    STATUS_RETIRED,
    STATUS_REVOKED,
    STATUS_SIGNED,
    STATUS_STALE,
    UNMEASURED,
    EntryState,
    LibraryAct,
    LibraryEntry,
    LibraryRefused,
    Provenance,
    ProvenStandard,
    apply,
    evidence_of,
    fold,
    is_person,
    quality_rows,
    signed_context,
    split_entry_id,
    stale_candidates,
    verify_library_chain,
    work_type_page,
    work_types_of,
)

ROOT = Path(__file__).resolve().parent.parent
ADA = "a" * 32  # a person's account id (32 hex)
BEN = "b" * 32
CAL = "c" * 32
DIGEST = "d" * 64
NEW_DIGEST = "e" * 64
COMMIT = "1" * 40


def entry(**over: object) -> LibraryEntry:
    base: dict[str, object] = {
        "repo": "alpha",
        "kind": "convention",
        "slug": "errors-wrap",
        "title": "Wrap errors with context",
        "statement": "Every returned error is wrapped with fmt.Errorf and %w, naming the operation.",
        "provenance": Provenance(kind="person", person=ADA),
        "proposed_by": ADA,
        "work_types": ("bug.fix",),
    }
    base.update(over)
    return LibraryEntry(**base)  # type: ignore[arg-type]


_N = [0]


def act(e: LibraryEntry, kind: str, actor: str, **body: object) -> LibraryAct:
    _N[0] += 1
    b: dict[str, object] = {"entry": e.content()} if kind == ACT_PROPOSE else dict(body)
    return LibraryAct(
        act_id=f"{_N[0]:032x}",
        repo=e.repo,
        entry_id=e.entry_id,
        version=e.version,
        act=kind,
        actor=actor,
        created=f"2026-09-27T10:{_N[0] % 60:02d}:00+00:00",
        body=b,
    )


def run(*acts: LibraryAct) -> EntryState:
    state: EntryState | None = None
    for a in acts:
        state = apply(state, a)
    assert state is not None
    return state


# --- the record ---------------------------------------------------------------------------


def test_every_entry_is_one_of_six_kinds_with_the_id_kind_slash_slug() -> None:
    assert KINDS == ("component", "work-type", "decision", "convention", "pattern", "standard")
    e = entry()
    assert e.entry_id == "convention/errors-wrap"
    assert split_entry_id(e.entry_id) == ("convention", "errors-wrap")
    with pytest.raises(ValueError, match="kind is one of"):
        entry(kind="note")
    with pytest.raises(ValueError, match="<kind>/<slug>"):
        split_entry_id("note/x")
    with pytest.raises(ValueError, match="slug"):
        entry(slug="Has Spaces")


def test_a_statement_is_at_most_400_characters_and_carries_no_code_or_secret() -> None:
    assert len(entry(statement="x" * 400).statement) == 400
    with pytest.raises(ValueError, match="at most 400"):
        entry(statement="x" * 401)
    with pytest.raises(ValueError, match="no code"):
        entry(statement="Use ```go\nerr := f()\n``` always")
    with pytest.raises(ValueError, match="no credential"):
        entry(statement="Deploy with ghp_" + "A" * 36)


def test_provenance_is_a_file_at_a_commit_graded_rows_or_a_person() -> None:
    f = Provenance(kind="file", path="docs/adr/0001.md", commit=COMMIT, digest=DIGEST)
    assert f.label() == f"docs/adr/0001.md at {COMMIT[:12]}"
    assert Provenance(kind="rows", rows=(DIGEST,)).label() == "1 graded row"
    with pytest.raises(ValueError, match="sha256"):
        Provenance(kind="file", path="a.md", commit=COMMIT)
    with pytest.raises(ValueError, match="inside the repository"):
        Provenance(kind="file", path="../etc/passwd", commit=COMMIT, digest=DIGEST)
    with pytest.raises(ValueError, match="graded rows"):
        Provenance(kind="rows")
    with pytest.raises(ValueError, match="the person who wrote"):
        Provenance(kind="person", person="mined:adr@1")


def test_proposed_by_is_a_person_a_miner_or_a_model_and_the_two_are_never_people() -> None:
    assert is_person(ADA)
    for process in ("mined:adr@1", "drafted:claude-sonnet-5", "system", "worker-1", ""):
        assert not is_person(process), process
    mined = Provenance(kind="file", path="docs/adr/0001.md", commit=COMMIT, digest=DIGEST)
    assert entry(provenance=mined, proposed_by="mined:adr@1").proposed_by == "mined:adr@1"
    assert entry(provenance=mined, proposed_by="drafted:m").proposed_by == "drafted:m"
    with pytest.raises(ValueError, match="proposed by"):
        entry(provenance=mined, proposed_by="mined:")
    with pytest.raises(ValueError, match="a person wrote"):
        entry(proposed_by="mined:adr@1")


def test_a_standard_names_its_iso_25010_characteristic_and_is_advisory_without_a_check() -> None:
    std = entry(kind="standard", slug="no-panics", characteristic="Reliability", check="go-vet")
    assert evidence_of(std, ["go-vet", "target_green"]) == "check"
    assert evidence_of(std, ["target_green"]) == "advisory"  # the repository never runs it
    assert evidence_of(replace(std, check=""), ["go-vet"]) == "advisory"
    with pytest.raises(ValueError, match="characteristic it refines"):
        entry(kind="standard", slug="s")
    with pytest.raises(ValueError, match="nine"):
        entry(kind="standard", slug="s", characteristic="Beauty")
    with pytest.raises(ValueError, match="only a standard or a convention"):
        entry(kind="decision", slug="d", check="go-vet")
    assert evidence_of(entry(kind="decision", slug="d"), ["x"]) == ""


def test_the_iso_vocabulary_is_the_nine_characteristics_of_the_quality_table() -> None:
    assert len(ISO_25010_CHARACTERISTICS) == 9
    try:
        qm = importlib.import_module("crb.core.quality_model")
    except ModuleNotFoundError:
        pytest.skip("stream C's quality table is not on this build (wired at integration)")
    assert tuple(c.name for c in qm.QUALITY_MODEL) == ISO_25010_CHARACTERISTICS


def test_a_work_type_names_a_global_parent_class_and_only_it_carries_slots() -> None:
    wt = entry(
        kind="work-type",
        slug="flag-fix",
        parent_class="bug.fix",
        examples=("abc1234",),
        slots=("flag_name",),
        work_types=(),
    )
    assert wt.parent_class == "bug.fix"
    with pytest.raises(ValueError, match="global parent"):
        entry(kind="work-type", slug="x", parent_class="nonsense")
    with pytest.raises(ValueError, match="only a work type"):
        entry(slots=("x",))


def test_any_change_to_the_content_is_a_new_version() -> None:
    e = entry()
    assert e.version == entry().version
    assert e.version != entry(statement=e.statement + " Always.").version
    assert e.version != entry(work_types=("bug.fix", "feature.add")).version


# --- the two-person rule -------------------------------------------------------------------


def test_the_person_who_proposes_is_the_sponsor_and_another_person_signs() -> None:
    e = entry()
    proposed = run(act(e, ACT_PROPOSE, ADA))
    assert (proposed.status, proposed.sponsor) == (STATUS_PROPOSED, ADA)
    signed = apply(proposed, act(e, ACT_SIGN, BEN))
    assert (signed.status, signed.sponsor, signed.approver) == (STATUS_SIGNED, ADA, BEN)
    assert signed.effect == UNMEASURED and signed.usable


def test_the_sponsor_can_never_sign_their_own_entry() -> None:
    e = entry()
    with pytest.raises(LibraryRefused) as exc:
        run(act(e, ACT_PROPOSE, ADA), act(e, ACT_SIGN, ADA))
    assert exc.value.code == "same_person"


def test_a_mined_proposal_needs_a_person_to_sponsor_it_before_another_signs() -> None:
    prov = Provenance(kind="file", path="docs/adr/0001.md", commit=COMMIT, digest=DIGEST)
    e = entry(kind="decision", slug="adr-0001", provenance=prov, proposed_by="mined:adr@1")
    proposed = run(act(e, ACT_PROPOSE, "mined:adr@1"))
    assert proposed.sponsor == ""
    with pytest.raises(LibraryRefused) as no_sponsor:
        apply(proposed, act(e, ACT_SIGN, BEN))
    assert no_sponsor.value.code == "no_sponsor"
    for machine in ("mined:adr@1", "drafted:claude-sonnet-5", "system"):
        with pytest.raises(LibraryRefused) as not_person:
            apply(proposed, act(e, ACT_SPONSOR, machine))
        assert not_person.value.code == "not_a_person"
    sponsored = apply(proposed, act(e, ACT_SPONSOR, ADA))
    with pytest.raises(LibraryRefused) as twice:
        apply(sponsored, act(e, ACT_SPONSOR, CAL))
    assert twice.value.code == "already_sponsored"
    with pytest.raises(LibraryRefused) as same:
        apply(sponsored, act(e, ACT_SIGN, ADA))
    assert same.value.code == "same_person"
    with pytest.raises(LibraryRefused) as model_signs:
        apply(sponsored, act(e, ACT_SIGN, "drafted:claude-sonnet-5"))
    assert model_signs.value.code == "not_a_person"
    assert apply(sponsored, act(e, ACT_SIGN, BEN)).status == STATUS_SIGNED


def test_a_signature_names_the_version_it_read_and_a_new_version_needs_a_new_one() -> None:
    e1 = entry()
    e2 = entry(statement=e1.statement + " Always.")
    state = run(act(e1, ACT_PROPOSE, ADA), act(e1, ACT_SIGN, BEN))
    state = apply(state, act(e2, ACT_PROPOSE, ADA))
    assert (state.status, state.entry.version) == (STATUS_PROPOSED, e2.version)
    with pytest.raises(LibraryRefused) as old:
        apply(state, act(e1, ACT_SIGN, BEN))
    assert old.value.code == "version_mismatch"
    with pytest.raises(LibraryRefused) as same:
        apply(state, act(e2, ACT_PROPOSE, ADA))
    assert same.value.code == "unchanged"


def test_revocation_and_retirement_are_appended_and_final() -> None:
    e = entry()
    signed = run(act(e, ACT_PROPOSE, ADA), act(e, ACT_SIGN, BEN))
    with pytest.raises(LibraryRefused) as why:
        apply(signed, act(e, ACT_REVOKE, CAL))
    assert why.value.code == "reason_missing"
    revoked = apply(signed, act(e, ACT_REVOKE, CAL, reason="superseded by ADR-0009"))
    assert revoked.status == STATUS_REVOKED and revoked.revoked == {
        "actor": CAL,
        "reason": "superseded by ADR-0009",
        "at": revoked.revoked["at"] if revoked.revoked else "",
    }
    assert not revoked.usable
    with pytest.raises(LibraryRefused) as final:
        apply(revoked, act(e, ACT_SIGN, BEN))
    assert final.value.code == "already_final"
    retired = apply(signed, act(e, ACT_RETIRE, CAL, reason="no longer true", by="person"))
    assert retired.status == STATUS_RETIRED and retired.retired
    assert retired.retired["by"] == "person"
    # a new proposal brings a final entry back, as a new proposal
    assert apply(revoked, act(e, ACT_PROPOSE, ADA)).status == STATUS_PROPOSED


def test_a_retirement_by_measurement_is_the_arm_readers_and_names_its_reading() -> None:
    e = entry()
    signed = run(act(e, ACT_PROPOSE, ADA), act(e, ACT_SIGN, BEN))
    body = {"by": "measurement", "reason": "the pairs favour the arm without it"}
    with pytest.raises(LibraryRefused) as no_reading:
        apply(signed, act(e, ACT_RETIRE, ACTOR_MEASUREMENT, **body))
    assert no_reading.value.code == "reading_missing"
    with pytest.raises(LibraryRefused) as person:
        apply(signed, act(e, ACT_RETIRE, BEN, reading_id="r1", **body))
    assert person.value.code == "reading_missing"
    measured = apply(signed, act(e, ACT_RETIRE, ACTOR_MEASUREMENT, reading_id="r1", **body))
    assert measured.retired and measured.retired["by"] == "measurement"
    assert measured.retired["reading_id"] == "r1"


# --- staleness -----------------------------------------------------------------------------


def _from_file() -> LibraryEntry:
    prov = Provenance(kind="file", path=".golangci.yml", commit=COMMIT, digest=DIGEST)
    return entry(slug="lint", provenance=prov, proposed_by="mined:lint@1", check="golangci-lint")


def test_an_entry_read_from_a_file_goes_stale_when_the_file_changes_until_signed_again() -> None:
    e = _from_file()
    signed = run(
        act(e, ACT_PROPOSE, "mined:lint@1"), act(e, ACT_SPONSOR, ADA), act(e, ACT_SIGN, BEN)
    )
    assert stale_candidates([signed], {".golangci.yml": DIGEST}) == []
    assert stale_candidates([signed], {}) == []  # an unread path is not a changed one
    [(cand, now)] = stale_candidates([signed], {".golangci.yml": NEW_DIGEST})
    assert (cand.entry_id, now) == (e.entry_id, NEW_DIGEST)
    stale = apply(signed, act(e, ACT_STALE, ADA, head_commit="2" * 40, digest=NEW_DIGEST))
    assert stale.status == STATUS_STALE and not stale.usable
    assert signed_context([stale]) == []
    with pytest.raises(LibraryRefused) as twice:
        apply(stale, act(e, ACT_STALE, ADA, head_commit="2" * 40, digest=NEW_DIGEST))
    assert twice.value.code == "file_unchanged"
    with pytest.raises(LibraryRefused) as own:
        apply(stale, act(e, ACT_SIGN, ADA))
    assert own.value.code == "same_person"
    resigned = apply(stale, act(e, ACT_SIGN, BEN))
    assert resigned.status == STATUS_SIGNED and resigned.acknowledged_digest == NEW_DIGEST
    # the file as re-signed is no longer a change; a deleted file is
    assert stale_candidates([resigned], {".golangci.yml": NEW_DIGEST}) == []
    assert [s.entry_id for s, _ in stale_candidates([resigned], {".golangci.yml": None})] == [
        e.entry_id
    ]
    with pytest.raises(LibraryRefused) as not_file:
        run(act(entry(), ACT_PROPOSE, ADA), act(entry(), ACT_STALE, ADA, digest=NEW_DIGEST))
    assert not_file.value.code == "not_from_a_file"


def test_a_file_gone_at_head_is_a_change_before_any_re_signature() -> None:
    # P-181: the empty digest (a file gone at head) once matched the empty acknowledged
    # digest of an entry never re-signed, so a deleted file left its entry signed
    e = _from_file()
    for before in (
        run(act(e, ACT_PROPOSE, "mined:lint@1"), act(e, ACT_SPONSOR, ADA), act(e, ACT_SIGN, BEN)),
        run(act(e, ACT_PROPOSE, "mined:lint@1"), act(e, ACT_SPONSOR, ADA)),
    ):
        assert before.acknowledged_digest == ""
        for gone in (None, ""):
            [(cand, now)] = stale_candidates([before], {".golangci.yml": gone})
            assert (cand.entry_id, now) == (e.entry_id, "")
        stale = apply(before, act(e, ACT_STALE, "system:library-freshness", digest=""))
        assert stale.status == STATUS_STALE and stale.stale is not None
        assert stale.stale["digest"] == ""


def test_only_signed_fresh_entries_are_signed_context() -> None:
    e1, e2, e3 = entry(slug="a1"), entry(slug="a2"), entry(slug="a3")
    states = [
        run(act(e1, ACT_PROPOSE, ADA)),
        run(act(e2, ACT_PROPOSE, ADA), act(e2, ACT_SIGN, BEN)),
        run(
            act(e3, ACT_PROPOSE, ADA), act(e3, ACT_SIGN, BEN), act(e3, ACT_REVOKE, BEN, reason="x")
        ),
    ]
    assert [s.entry_id for s in signed_context(states)] == ["convention/a2"]


# --- the chain -----------------------------------------------------------------------------


def _chain(acts: list[LibraryAct]) -> list[LibraryAct]:
    out, prev = [], GENESIS_HASH
    for a in acts:
        c = a.chained(prev)
        out.append(c)
        prev = c.row_hash
    return out


def test_the_acts_are_hash_chained_and_a_tampered_act_is_found() -> None:
    e = entry()
    chain = _chain([act(e, ACT_PROPOSE, ADA), act(e, ACT_SIGN, BEN)])
    assert verify_library_chain(chain) == 2
    assert LibraryAct.from_dict(chain[1].to_dict()) == chain[1]
    forged = replace(chain[1], actor=ADA)  # swap the signer for the sponsor
    with pytest.raises(LedgerIntegrityError, match="row_hash"):
        verify_library_chain([chain[0], forged])
    with pytest.raises(LedgerIntegrityError, match="prev_hash"):
        verify_library_chain([chain[1]])


def test_a_fold_that_meets_an_act_the_rule_refuses_raises_rather_than_skipping() -> None:
    e = entry()
    assert fold([act(e, ACT_PROPOSE, ADA)])[e.entry_id].status == STATUS_PROPOSED
    with pytest.raises(LedgerIntegrityError, match="no longer applies"):
        fold([act(e, ACT_PROPOSE, ADA), act(e, ACT_SIGN, ADA)])


# --- never a brief -------------------------------------------------------------------------

BRIEF_PACKAGES = ("builders", "factory", "intake")
BRIEF_CORE = ("run", "playbook", "finish_gate", "learn", "prevention")
LIBRARY_MODULES = {"crb.core.library", "crb.store.library", "crb.server.routes.library"}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def test_no_entry_reaches_a_builders_brief_nothing_that_composes_one_imports_the_library() -> None:
    """ADR-0026 item 10: an entry reaches a brief only inside a measured arm (Wave 5, off by
    default). Every module that composes, runs or feeds a brief is walked, and the
    import-linter contract that refuses the import (indirect ones too) is pinned."""
    src = ROOT / "src" / "crb"
    files = [p for pkg in BRIEF_PACKAGES for p in (src / pkg).rglob("*.py")]
    files += [src / "core" / f"{m}.py" for m in BRIEF_CORE]
    assert len(files) > 20
    offenders = {str(p.relative_to(ROOT)): _imports(p) & LIBRARY_MODULES for p in files}
    assert {k: v for k, v in offenders.items() if v} == {}
    contracts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "importlinter"
    ]["contracts"]
    [guard] = [c for c in contracts if c["name"] == "library entries never reach a brief"]
    assert guard["type"] == "forbidden"
    assert set(guard["forbidden_modules"]) == LIBRARY_MODULES
    assert {f"crb.{p}" for p in BRIEF_PACKAGES} <= set(guard["source_modules"])
    assert {f"crb.core.{m}" for m in BRIEF_CORE} <= set(guard["source_modules"])
    assert not guard.get("allow_indirect_imports", False)


def test_a_signed_entrys_statement_is_absent_from_the_brief_a_build_composes() -> None:
    """The behaviour, not only the imports: a brief composed for a replay carries no field
    for library entries and none of a signed entry's words."""
    from crb.builders.base import BuildBrief

    e = entry(statement="Always call Validate before Save; the library says so.")
    signed = run(act(e, ACT_PROPOSE, ADA), act(e, ACT_SIGN, BEN))
    assert signed.usable
    assert not {f for f in BuildBrief.__dataclass_fields__ if "library" in f}
    brief = BuildBrief(
        subject="fix: validate", message="fix: validate", repo="alpha", language="go"
    )
    assert e.statement not in repr(brief)


# --- the page per work type ----------------------------------------------------------------

TASKS = [
    {"task_id": "1" * 40, "capability_class": "bug.fix", "size": "XS", "subject": "fix: a"},
    {"task_id": "2" * 40, "capability_class": "bug.fix", "size": "S", "subject": "fix: b"},
    {"task_id": "3" * 40, "capability_class": "docs.update", "size": "XS", "subject": "docs"},
]
SLOTS = [{"name": "expected_behavior", "question": "What should happen?", "kind": "structural"}]


def _states() -> dict[str, EntryState]:
    signed = entry()
    proposed = entry(slug="unsigned")
    std = entry(kind="standard", slug="vet", characteristic="Maintainability", check="go-vet")
    other = entry(slug="docs-only", work_types=("docs.update",))
    acts = [
        act(signed, ACT_PROPOSE, ADA),
        act(signed, ACT_SIGN, BEN),
        act(proposed, ACT_PROPOSE, ADA),
        act(std, ACT_PROPOSE, ADA),
        act(std, ACT_SIGN, BEN),
        act(other, ACT_PROPOSE, ADA),
        act(other, ACT_SIGN, BEN),
    ]
    return fold(acts)


def test_the_page_says_what_the_work_type_is_what_a_ticket_carries_and_its_signed_context() -> None:
    page = work_type_page(
        "alpha", "bug.fix", _states(), tasks=TASKS, catalogue=SLOTS,
        runnable_checks=["target_green"], quality=None,
    )  # fmt: skip
    assert page["definition"].startswith("Repairs a defect")
    assert page["definition_source"] == "global"
    assert [x["sha"] for x in page["examples"]] == ["1" * 40, "2" * 40]
    assert page["ticket_slots"] == SLOTS
    ids = [c["entry_id"] for c in page["context"]]
    assert ids == ["convention/errors-wrap", "standard/vet"]  # signed, in scope, never unsigned
    c = page["context"][0]
    assert (c["sponsor"], c["approver"], c["effect"]) == (ADA, BEN, "unmeasured")
    assert c["provenance_label"] == "written by a person" and c["signed_at"]
    conv, std = page["quality"]["standards"]  # conventions and standards, with their evidence
    assert (conv["kind"], conv["evidence"]) == ("convention", "advisory")
    assert (std["characteristic"], std["evidence"]) == ("Maintainability", "advisory")
    assert page["quality"]["served"] is False


def test_each_size_reads_no_proven_standard_and_names_the_next_measurement_by_default() -> None:
    page = work_type_page(
        "alpha", "bug.fix", {}, tasks=TASKS, catalogue=[], runnable_checks=[], quality=None
    )
    xs = page["sizes"][0]
    assert (xs["size"], xs["standard"], xs["tasks"]) == ("XS", None, 1)
    assert (
        "first look needs 20 distinct commits; 1 commit of this kind and size mined" in xs["next"]
    )
    assert [s["size"] for s in page["sizes"]] == ["XS", "S", "M", "L", "XL"]


def test_a_proven_standard_is_shown_with_its_arm_n_interval_and_apparatus() -> None:
    def reader(repo: str, cls: str, size: str) -> ProvenStandard | None:
        assert (repo, cls) == ("alpha", "bug.fix")
        return (
            ProvenStandard("S1@gpt-oss-120b", 20, 20, 0.839, 1.0, "2.4") if size == "XS" else None
        )

    page = work_type_page(
        "alpha", "bug.fix", {}, tasks=TASKS, catalogue=[], runnable_checks=[], quality=None,
        reader=reader,
    )  # fmt: skip
    xs, s = page["sizes"][0], page["sizes"][1]
    assert xs["standard"]["arm"] == "S1@gpt-oss-120b" and xs["standard"]["apparatus"] == "2.4"
    assert (xs["standard"]["n"], xs["standard"]["ci_low"], xs["next"]) == (20, 0.839, "")
    assert s["standard"] is None and s["next"]


def test_the_quality_section_reads_the_table_it_is_given_against_the_switched_on_checks() -> None:
    class Ev:
        def __init__(self, check: str) -> None:
            self.check, self.label, self.sub, self.runs = check, check, "sub", "always"

    class Ch:
        def __init__(self, name: str, counted: tuple[Ev, ...]) -> None:
            self.name, self.counted, self.note = name, counted, ""

    model = (
        Ch("Functional suitability", (Ev("target_green"),)),
        Ch("Maintainability", (Ev("repo_lint_clean"),)),
    )
    rows = quality_rows(model, ["target_green"])
    assert rows is not None
    assert [(r["characteristic"], r["evidenced"]) for r in rows] == [
        ("Functional suitability", True),
        ("Maintainability", False),
    ]
    assert quality_rows(None, ["target_green"]) is None


def test_a_signed_work_type_entry_defines_its_own_page_and_the_index_lists_it() -> None:
    wt = entry(
        kind="work-type", slug="flag-fix", title="Fix a flag", parent_class="bug.fix",
        examples=("abcdef1",), slots=("flag_name",), work_types=(),
        statement="A defect in how one command-line flag is parsed or defaulted.",
    )  # fmt: skip
    states = fold([act(wt, ACT_PROPOSE, ADA)])
    with pytest.raises(KeyError):  # an unsigned work type has no page
        work_type_page(
            "alpha", "flag-fix", states, tasks=TASKS, catalogue=[], runnable_checks=[], quality=None
        )
    states = fold([act(wt, ACT_PROPOSE, ADA), act(wt, ACT_SIGN, BEN)])
    page = work_type_page(
        "alpha", "flag-fix", states, tasks=TASKS, catalogue=[], runnable_checks=[], quality=None
    )
    assert (page["title"], page["parent_class"], page["signed_slots"]) == (
        "Fix a flag",
        "bug.fix",
        ["flag_name"],
    )
    assert page["examples"][0]["sha"] == "abcdef1"
    listed = {w["slug"]: w for w in work_types_of(states, TASKS)}
    assert listed["flag-fix"]["status"] == "signed" and listed["bug.fix"]["tasks"] == 2
    assert listed["docs.update"]["status"] == "global"
