"""One brief composer for replay and the factory, and the leak guard on every context line.

ADR-0026 items 1 and 7. Every build brief — a replay attempt's (``crb.builders.adapter``)
and a factory item's (``crb.factory.build``) — comes from :func:`compose`, from its
**context arm** (the pre-registered id of what the builder is given: ``A0`` the ticket
only, ``S1@<author>`` the ticket and an authored failing test, ``S2`` the ticket and a
person's failing test, ``S3`` the ticket and the commit's own tests, with ``+L`` when the
repository's loop switch is part of the arm) and a :class:`Ticket`. Nothing else composes a
brief, so replay measures what manufacture sends: two briefs of one arm differ only by the
ticket's source.

The composer stamps the arm (``labels.context_arm``) and the brief's **provenance** — shown
and filterable, never a pooling key:

=================  ===================================================================
``ctx_ticket``     ``message`` (a replay's commit message) or ``ticket@<date>`` (a
                   factory item as registered)
``ctx_brief``      sha256 of the composed parts (what the builder read)
``ctx_harness``    sha256 of the harness command
``ctx_rules``      sha256 of the protocol rules
``ctx_author``     the test author's provider stamp, on an ``S1`` brief
``ctx_library``    digest of the library entries' ids and versions, when any
``ctx_refused``    how many context lines the leak guard refused
=================  ===================================================================

**The leak guard** (ADR-0026 item 7). A context line — a structural fact, a learned
playbook line, a library entry — never names what the commit introduced:
:func:`novel_tokens` computes, harness-side, the identifiers and literals present in the
gold post-image of the changed files — the commit's source AND its own tests — and absent
from the whole parent tree, and
:func:`compose` refuses every line naming one, counting it on the row; the builder never
sees the tokens or the diff that powers the check. A retrospective brief (a replay) takes a
fact or library entry only when it was produced mechanically — no person's edit or
selection — at or before the reading's pool began (:func:`admit_retrospective`). Learned
lines are held out and time-ordered before they reach the composer
(:func:`crb.core.playbook.taught_before`).

Navigation
----------
What it is:   The one brief composer (``compose``), the context-arm name (``context_arm_for``,
              a seam until stream R's ``crb.core.context_arm`` lands), the leak guard
              (``novel_tokens``, ``refuse_novel``, ``admit_retrospective``), the replay
              ``S1`` arm's hook (``S1Arm``) and the rule for which factory ``S2`` rows a
              reading may count (``counts_as_s2_first_attempt``).
What it does: Builds every replay and factory ``BuildBrief`` from one arm and one ticket,
              refuses any context line naming a token the commit introduced, admits a
              retrospective fact or library entry only when it was produced mechanically
              before the pool began, and stamps the arm and its provenance on the row.
How:          Pure functions over strings plus one ``git`` read (``novel_tokens``: the gold
              post-image against the parent tree, harness-side); ``BuildBrief`` does the
              brief's own validation (a blind brief discloses no test).
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 1, 7 and 8),
              docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/adapter.py (the replay brief, the ``S1`` arm),
              src/crb/factory/build.py (the factory brief), src/crb/builders/base.py
              (``BuildBrief``, ``DEFAULT_RULES``), src/crb/core/playbook.py (the learned lines'
              held-out and time-order rules), src/crb/factory/loop.py (the factory's arm)
Tested by:    tests/test_builders_brief.py, tests/test_replay_s1_arm.py
Touch when:   a context modifier joins ADR-0026 item 1's grammar (``context_arm_for`` and a
              provenance label); stream R's context-arm module lands (replace
              ``context_arm_for``'s body with R's).
Claims:       an arm names what the brief carried, never how good it was; only a registered
              reading of the arm says that (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.builders.base import DEFAULT_RULES, BuildBrief
from crb.core import context_arm as _arms
from crb.core.git import GitRepo
from crb.core.grade import MODE_BLIND
from crb.core.spec import RepoConfig

#: The arm grammar is the core's, ONE vocabulary (``crb.core.context_arm``, ADR-0026 item 1):
#: the composer names its bases and labels through it, so a brief and a ledger row can never
#: spell an arm two ways.
ARM_A0 = _arms.BASE_A0
ARM_S1 = _arms.BASE_S1
ARM_S2 = _arms.BASE_S2
ARM_S3 = _arms.BASE_S3
BASES: tuple[str, ...] = _arms.BASES
MODIFIER_LOOP = _arms.MOD_LOOP

#: The provenance labels :func:`compose` stamps (ADR-0026 item 1), and the arm label.
LABEL_CONTEXT_ARM = _arms.LABEL_CONTEXT_ARM
LABEL_CTX_TICKET = _arms.LABEL_CTX_TICKET
LABEL_CTX_BRIEF = _arms.LABEL_CTX_BRIEF
LABEL_CTX_HARNESS = _arms.LABEL_CTX_HARNESS
LABEL_CTX_RULES = _arms.LABEL_CTX_RULES
LABEL_CTX_AUTHOR = _arms.LABEL_CTX_AUTHOR
LABEL_CTX_LIBRARY = _arms.LABEL_CTX_LIBRARY
LABEL_CTX_REFUSED = _arms.LABEL_CTX_REFUSED
CTX_LABELS: tuple[str, ...] = (
    LABEL_CTX_TICKET,
    LABEL_CTX_BRIEF,
    LABEL_CTX_HARNESS,
    LABEL_CTX_RULES,
    LABEL_CTX_AUTHOR,
    LABEL_CTX_LIBRARY,
    LABEL_CTX_REFUSED,
)
#: ``ctx_ticket`` for a replay: the commit message stands in for the ticket.
TICKET_MESSAGE = "message"

#: How a factory ``S2`` row was graded (ADR-0026 items 2 and 8): ``held_out`` only when a
#: second person's acceptance tests, kept outside the builder's tree, were graded too
#: (``product.truth.215`` — not built yet); ``none`` when the grade read only the test the
#: builder saw. Only ``held_out`` makes an ``S2`` row a routing first attempt.
LABEL_ACCEPTANCE = "acceptance"
ACCEPTANCE_HELD_OUT = "held_out"
ACCEPTANCE_NONE = "none"

#: The shortest identifier the leak guard compares; shorter words are too common to say
#: anything about the commit (the playbook's leak gate uses the same floor).
NOVEL_MIN = 4
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STRING_RE = re.compile(r"\"([^\"\\\n]{3,200})\"|'([^'\\\n]{3,200})'")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])(\d{2,})(?![A-Za-z0-9_])")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def context_arm_for(
    *,
    base: str,
    author: str = "",
    facts_drafter: str = "",
    library_version: str = "",
    plus_l: bool = False,
) -> str:
    """The arm id a brief carried, in ADR-0026 item 1's grammar — the base (``S1`` names its
    test author's canonical model, ``S1@<author>``), then ``+facts@<drafter>``,
    ``+library@<version>`` and ``+L`` in that order — built and checked by the core's
    :class:`crb.core.context_arm.ContextArm`, so the composer and the ledger's
    ``row_labels_at_write`` spell every arm the one way."""
    if base not in BASES:
        raise ValueError(f"a context arm's base is one of {BASES}, got {base!r}")
    if base == ARM_S1 and not author:
        raise ValueError("an S1 arm names its test author's canonical model (S1@<author>)")
    return _arms.ContextArm(
        base,
        author=author if base == ARM_S1 else "",
        facts=facts_drafter,
        library=library_version,
        loop=plus_l,
    ).id


def arm_base(arm: str) -> str:
    """The base of an arm id: ``S1@t1+L`` → ``S1``."""
    return arm.split("+", 1)[0].split("@", 1)[0]


def counts_as_s2_first_attempt(labels: Mapping[str, str]) -> bool:
    """Whether a factory row may count toward an ``S2`` reading (ADR-0026 items 2 and 8):
    only an ``S2`` row that carries POSITIVE evidence of held-out acceptance grading. A row
    graded only on the test the builder saw is clean almost by construction, so the
    absence of the stamp — or ``none`` — never counts. The reading (stream R) reads this."""
    return (
        arm_base(labels.get(LABEL_CONTEXT_ARM, "")) == ARM_S2
        and labels.get(LABEL_ACCEPTANCE, "") == ACCEPTANCE_HELD_OUT
    )


def arm_carries_loop(arm: str) -> bool:
    """Whether the arm's id carries ``+L`` — the loop's overlay and lines are part of it."""
    return MODIFIER_LOOP[1:] in arm.split("+")[1:]


# --- the ticket and the context -----------------------------------------------------------


@dataclass(frozen=True)
class Ticket:
    """What the builder is told the change is: a subject, the text, and where it came from
    (``message`` for a replay's commit message, ``ticket@<date>`` for a registered item)."""

    subject: str
    message: str
    source: str = TICKET_MESSAGE


@dataclass(frozen=True)
class ContextEntry:
    """A fact or library entry offered to a brief, with its provenance: when it was
    produced and whether mechanically (a pinned process, no person's edit or selection)."""

    entry_id: str
    text: str
    version: str = ""
    produced_at: str = ""
    mechanical: bool = False


def admit_retrospective(
    entries: Iterable[ContextEntry], *, pool_began: str
) -> tuple[list[ContextEntry], list[str]]:
    """``(admitted, refused ids)`` for a RETROSPECTIVE brief (ADR-0026 item 7): an entry
    reaches it only when it was produced mechanically, at or before the reading's pool
    began. A person-written entry, or one produced after (it may have seen the answer), is
    refused — whatever it says."""
    admitted: list[ContextEntry] = []
    refused: list[str] = []
    for e in entries:
        ok = e.mechanical and bool(e.produced_at) and bool(pool_began)
        if ok and e.produced_at <= pool_began:
            admitted.append(e)
        else:
            refused.append(e.entry_id)
    return admitted, refused


# --- the leak guard -----------------------------------------------------------------------


def _code_tokens(text: str) -> tuple[set[str], set[str]]:
    """``(identifiers, literals)`` of a source text: identifiers of at least
    :data:`NOVEL_MIN` characters, string literals of three or more characters and numbers
    of two or more digits."""
    idents = {m.group(0) for m in _IDENT_RE.finditer(text) if len(m.group(0)) >= NOVEL_MIN}
    literals: set[str] = set()
    for m in _STRING_RE.finditer(text):
        literals.add(m.group(1) or m.group(2))
    literals |= {m.group(1) for m in _NUMBER_RE.finditer(text)}
    return idents, literals


def _show(repo: GitRepo, rev: str, path: str) -> str:
    try:
        return repo.show_file(rev, path) or ""
    except Exception:
        return ""


#: More candidates than this and the parent-tree read is skipped: every candidate stays
#: novel (the guard fails closed rather than build an unbounded command line).
MAX_CANDIDATES = 2000


def novel_tokens(
    repo: GitRepo, *, parent: str, commit: str, paths: Sequence[str]
) -> frozenset[str]:
    """The identifiers and literals the commit introduced — present in the gold post-image
    of ``paths`` and absent from the WHOLE parent tree — computed harness-side, so the
    builder never sees the diff that powers the check (ADR-0026 item 7). One ``git grep``
    over the parent tree decides which candidates the parent already held."""
    candidates: set[str] = set()
    for path in paths:
        after_i, after_l = _code_tokens(_show(repo, commit, path))
        before_i, before_l = _code_tokens(_show(repo, parent, path))
        candidates |= (after_i - before_i) | (after_l - before_l)
    if not candidates:
        return frozenset()
    ordered = sorted(candidates)
    if len(ordered) > MAX_CANDIDATES:
        return frozenset(candidates)
    try:
        found = repo.run(
            "grep",
            "-h",
            "-o",
            "-w",
            "-F",
            *[a for tok in ordered for a in ("-e", tok)],
            parent,
            check=False,
        ).stdout
    except Exception:  # cannot read the parent tree: every candidate stays novel (fail closed)
        return frozenset(candidates)
    seen = {line.strip() for line in (found or "").splitlines() if line.strip()}
    return frozenset(c for c in candidates if c not in seen)


def names_novel(line: str, novel: frozenset[str]) -> bool:
    """Whether a context line names a token the commit introduced: an identifier as a whole
    word, a literal as a substring."""
    if not novel:
        return False
    words = set(_IDENT_RE.findall(line))
    return any(tok in words or (not tok.isidentifier() and tok in line) for tok in novel)


def refuse_novel(lines: Iterable[str], novel: frozenset[str]) -> tuple[list[str], list[str]]:
    """``(kept, refused)``: every context line naming a novel token is refused."""
    kept: list[str] = []
    refused: list[str] = []
    for ln in lines:
        (refused if names_novel(ln, novel) else kept).append(ln)
    return kept, refused


# --- the composer -------------------------------------------------------------------------


@dataclass(frozen=True)
class Composed:
    """A composed brief, the labels it stamps, and the lines the guard refused (kept off the
    brief and never shown to the builder; only their count reaches the row)."""

    brief: BuildBrief
    labels: Mapping[str, str]
    refused: tuple[str, ...] = ()
    library: tuple[ContextEntry, ...] = field(default_factory=tuple)


def compose(
    arm: str,
    ticket: Ticket,
    *,
    repo: str,
    language: str,
    mode: str,
    config: RepoConfig | None = None,
    test_files: Sequence[str] = (),
    target_tests: Sequence[str] = (),
    test_command: str = "",
    harness_command: str = "",
    finish_checks: Sequence[str] = (),
    facts: Sequence[str] = (),
    learned: Sequence[str] = (),
    library: Sequence[ContextEntry] = (),
    novel: frozenset[str] = frozenset(),
    author: str = "",
    rules: str = DEFAULT_RULES,
    retrospective: bool = False,
    pool_began: str = "",
    root: str = "",
) -> Composed:
    """THE brief composer (ADR-0026 items 1 and 7): the arm's brief for one ticket.

    ``facts`` and ``learned`` are context lines (structural facts; the loop's playbook lines,
    already held out and time-ordered); ``library`` the entries the arm carries. A
    retrospective brief admits a library entry only through :func:`admit_retrospective`,
    and refuses every bare fact (it carries no provenance to admit it by);
    every context line naming a ``novel`` token is refused and counted. A blind brief
    discloses no test (``BuildBrief`` refuses one that would). ``root`` — the worktree the
    brief is for — is kept out of the provenance hashes."""
    admitted = list(library)
    lib_refused: list[str] = []
    bare_refused: list[str] = []
    if retrospective:
        admitted, lib_refused = admit_retrospective(library, pool_began=pool_began)
        # a bare fact carries no provenance, so it cannot show it was produced mechanically
        # before the pool began: a retrospective brief takes facts only as library entries
        bare_refused, facts = list(facts), ()
    kept_facts, refused_facts = refuse_novel(facts, novel)
    kept_learned, refused_learned = refuse_novel(learned, novel)
    lib_texts, refused_lib = refuse_novel([e.text for e in admitted], novel)
    kept_entries = tuple(e for e in admitted if e.text in lib_texts)
    blind = mode == MODE_BLIND
    brief = BuildBrief(
        subject=ticket.subject,
        message=ticket.message or ticket.subject,
        repo=repo,
        language=language,
        mode=mode,
        test_files=() if blind else tuple(test_files),
        target_tests=() if blind else tuple(target_tests),
        test_command="" if blind else test_command,
        harness_command=harness_command,
        spec_facts=(*kept_facts, *lib_texts),
        rules=rules,
        config=config,
        finish_checks=tuple(finish_checks),
        playbook=tuple(kept_learned),
    )
    refused = (*bare_refused, *refused_facts, *refused_learned, *refused_lib)
    parts = {
        "subject": brief.subject,
        "message": brief.message,
        "mode": brief.mode,
        "test_files": list(brief.test_files),
        "target_tests": list(brief.target_tests),
        "spec_facts": list(brief.spec_facts),
        "playbook": list(brief.playbook),
        "finish_checks": list(brief.finish_checks),
    }
    labels: dict[str, str] = {
        LABEL_CONTEXT_ARM: arm,
        LABEL_CTX_TICKET: ticket.source,
        LABEL_CTX_BRIEF: _sha(json.dumps(parts, sort_keys=True, ensure_ascii=False)),
        LABEL_CTX_RULES: _sha(rules),
        LABEL_CTX_REFUSED: str(len(refused) + len(lib_refused)),
    }
    if harness_command:
        # the worktree's own path is where the build runs, not context: two trees of one
        # arm carry the same harness (``root`` is replaced before hashing)
        labels[LABEL_CTX_HARNESS] = _sha(
            harness_command.replace(root, "<worktree>") if root else harness_command
        )
    if author:
        labels[LABEL_CTX_AUTHOR] = author
    if kept_entries:
        labels[LABEL_CTX_LIBRARY] = _sha(
            json.dumps(sorted([e.entry_id, e.version] for e in kept_entries))
        )[:16]
    return Composed(brief=brief, labels=labels, refused=refused, library=kept_entries)


# --- the replay S1 arm's hook -------------------------------------------------------------

#: ``(sealed workspace, subject, message) -> (path, content)`` — the configured test author
#: writing one failing test in a sealed one-commit checkout of the parent. Bound by the
#: worker around the factory's test author; the builders layer never imports the factory.
AuthorFn = Callable[[Any, str, str], tuple[str, str]]


@dataclass(frozen=True)
class S1Arm:
    """A replay run on arm ``S1@<author>`` (ADR-0026 item 1): the test author (whose model
    is never a build rung's — DL-050, DL-059 C3) writes one failing test in a sealed
    checkout of the parent from the message and the parent's example tests; it must prove
    RED at the parent; the builder builds against it; the grade is the commit's held-out
    tests with the authored test removed first. ``author_model`` is the author's canonical
    model (the arm names it); ``author_stamp`` its provider stamp (``ctx_author``)."""

    author: AuthorFn
    author_model: str
    author_stamp: str = ""

    @property
    def arm(self) -> str:
        return context_arm_for(base=ARM_S1, author=self.author_model)


__all__ = [
    "ACCEPTANCE_HELD_OUT",
    "ACCEPTANCE_NONE",
    "ARM_A0",
    "ARM_S1",
    "ARM_S2",
    "ARM_S3",
    "BASES",
    "CTX_LABELS",
    "LABEL_ACCEPTANCE",
    "LABEL_CONTEXT_ARM",
    "LABEL_CTX_AUTHOR",
    "LABEL_CTX_BRIEF",
    "LABEL_CTX_HARNESS",
    "LABEL_CTX_LIBRARY",
    "LABEL_CTX_REFUSED",
    "LABEL_CTX_RULES",
    "LABEL_CTX_TICKET",
    "MODIFIER_LOOP",
    "NOVEL_MIN",
    "TICKET_MESSAGE",
    "AuthorFn",
    "Composed",
    "ContextEntry",
    "S1Arm",
    "Ticket",
    "admit_retrospective",
    "arm_base",
    "arm_carries_loop",
    "compose",
    "context_arm_for",
    "counts_as_s2_first_attempt",
    "names_novel",
    "novel_tokens",
    "refuse_novel",
]
