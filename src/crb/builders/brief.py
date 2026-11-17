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
``ctx_delivered``  on a context-set arm (ADR-0050): how many entries reached the brief
``ctx_chars``      on a context-set arm: the characters of the entries that reached it
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

**Context-set arms** (ADR-0050 item 4). On an arm whose library NAME is a context set
(``crb.core.context_arm.ctx_set_name``) the admission is derived from the arm alone: a
hindsight set (``ctx.oracle*``) skips only the retrospective time rule — never the leak guard
or the bare-fact refusal; a mechanical set (``ctx.mech*``) is admitted by knowledge boundary
(:func:`admit_at_parent`: mechanical and drafted at the task's parent commit). Any other
library NAME keeps :func:`admit_retrospective` unchanged.

**Stated-requirement arms** (ADR-0052, which amends ADR-0050 items 3 and 4 for the ``req``
source ONLY). On a ``ctx.req*`` arm an entry that carries stated items is checked by
:func:`req_guard` instead of :func:`refuse_novel`: it re-renders the text from the items, holds
the fixed limits, and refuses a code block, a disclosure that is not exactly one token, an
undeclared novel token, a misstated provenance, a held-out test's name (a helper's or
fixture's too) or path, an eight-token span copied from the change (filler words and item
boundaries do not break it), or a signature item carrying a body. Its declared novel tokens
reach the brief — that is the amendment. Every other line of the brief — any entry without
items, every fact and every learned line — keeps :func:`refuse_novel` exactly as before, on a
``req`` arm too.

**Accepted-plan arms** (ADR-0054). On a ``ctx.plan*`` arm the entries are admitted at the
task's parent commit without the mechanical stamp (a plan is accepted, not mechanical), and an
entry carrying a plan is checked by :func:`plan_guard`: it re-renders the text from the plan,
holds the fixed limits, and refuses a code block, a held-out test's name or path, an
eight-token span copied from the change's added test lines or its added source lines, or an
asserted literal. A guarded plan is withheld WHOLE. A kept plan reaches ``BuildBrief.plan``,
never ``spec_facts``; the change's novel tokens it names are counted (``ctx_plan_novel``), not
refused — a plan written before the build may name what the build will add.

Navigation
----------
What it is:   The one brief composer (``compose``), the context-arm name (``context_arm_for``,
              a seam until stream R's ``crb.core.context_arm`` lands), the leak guard
              (``novel_tokens``, ``refuse_novel``, ``admit_retrospective``,
              ``admit_at_parent``), the stated-requirement guard (``req_guard`` over a
              harness-side ``GoldView``, ``gold_view``), the accepted-plan guard
              (``plan_guard``, ``plan_novel``), the replay
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
              docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0050-context-set-arms.md (item 4, the context-set admission),
              docs/adr/0052-stated-requirement-arms.md (``req_guard``, the req amendment),
              docs/adr/0054-accepted-plan-context-arm.md (``plan_guard``, the plan arm)
Works with:   src/crb/builders/adapter.py (the replay brief, the ``S1`` arm),
              src/crb/factory/build.py (the factory brief), src/crb/builders/base.py
              (``BuildBrief``, ``DEFAULT_RULES``), src/crb/core/playbook.py (the learned lines'
              held-out and time-order rules), src/crb/factory/loop.py (the factory's arm)
Tested by:    tests/test_builders_brief.py, tests/test_replay_s1_arm.py,
              tests/test_brief_req_guard.py, tests/test_brief_plan_guard.py,
              tests/test_brief_text_guard_equivalence.py
Touch when:   never for a new repository; a context modifier joins ADR-0026 item 1's grammar
              (``context_arm_for`` and a provenance label); stream R's context-arm module lands
              (replace ``context_arm_for``'s body with R's).
Claims:       an arm names what the brief carried, never how good it was; only a registered
              reading of the arm says that (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.builders.base import DEFAULT_RULES, BuildBrief
from crb.core import acceptance as _acceptance
from crb.core import context_arm as _arms
from crb.core import plan as _plan
from crb.core import stated as _stated
from crb.core.git import GitRepo
from crb.core.grade import MODE_BLIND
from crb.core.spec import RepoConfig, is_test_path

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
LABEL_CTX_DELIVERED = _arms.LABEL_CTX_DELIVERED
LABEL_CTX_CHARS = _arms.LABEL_CTX_CHARS
LABEL_CTX_REQ_REFUSED = _arms.LABEL_CTX_REQ_REFUSED
LABEL_CTX_PLAN_REFUSED = _arms.LABEL_CTX_PLAN_REFUSED
LABEL_CTX_PLAN_NOVEL = _arms.LABEL_CTX_PLAN_NOVEL
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
#: second person's acceptance tests, kept outside the builder's tree, were graded too;
#: ``none`` when the grade read only the test the builder saw. The vocabulary is the core's
#: (``crb.core.acceptance``), ONE spelling for the writer and every reader (P-690).
LABEL_ACCEPTANCE = _acceptance.LABEL_ACCEPTANCE
ACCEPTANCE_HELD_OUT = _acceptance.ACCEPTANCE_HELD_OUT
ACCEPTANCE_NONE = _acceptance.ACCEPTANCE_NONE

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
    only an ``S2`` row that carries POSITIVE evidence of held-out acceptance grading — the
    core's one rule, :func:`crb.core.acceptance.held_out_graded`, which the reading and the
    ledger's routing first attempts apply too (P-690)."""
    return _acceptance.held_out_graded(labels)


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
    produced and whether mechanically (a pinned process, no person's edit or selection).
    ``source_rev`` is the commit a mechanical context-set entry was drafted at — its
    knowledge boundary (ADR-0050 item 4); empty for every other entry. ``items`` and
    ``structure`` are a stated-requirement entry's (ADR-0052): ``text`` must be
    ``structure``'s rendering of ``items``, which :func:`req_guard` re-checks. ``plan`` is an
    accepted-plan entry's (ADR-0054): ``text`` must be its rendering, which :func:`plan_guard`
    re-checks; ``source_rev`` is then the parent commit the plan was written at."""

    entry_id: str
    text: str
    version: str = ""
    produced_at: str = ""
    mechanical: bool = False
    source_rev: str = ""
    items: tuple[_stated.StatedItem, ...] = ()
    structure: str = ""
    plan: _plan.PlanBody | None = None

    @property
    def planned(self) -> bool:
        """An accepted-plan entry (ADR-0054): it carries a plan."""
        return self.plan is not None


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


def admit_at_parent(
    entries: Iterable[ContextEntry], parent_rev: str, *, require_mechanical: bool = True
) -> tuple[list[ContextEntry], list[str]]:
    """``(admitted, refused ids)`` for a MECHANICAL context-set arm (``ctx.mech*``, ADR-0050
    item 4; ADR-0026 item 1's ``+facts@<drafter>`` condition): an entry is admitted by its
    knowledge boundary, not by wall-clock time — only when it was produced mechanically and
    records the task's parent commit as its ``source_rev``. Anything else is refused.

    An accepted-plan arm (``ctx.plan*``, ADR-0054) passes ``require_mechanical=False``: a plan
    is written and accepted by people or a pinned model, never stamped mechanical, and is
    admitted by the same knowledge boundary alone (its ``source_rev`` is the parent)."""
    admitted: list[ContextEntry] = []
    refused: list[str] = []
    for e in entries:
        ok = e.mechanical or not require_mechanical
        if ok and bool(parent_rev) and e.source_rev == parent_rev:
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


class GoldReadError(Exception):
    """A blob the commit holds could not be read: the gold view would be incomplete."""


def _show_strict(repo: GitRepo, rev: str, path: str) -> str:
    """``path``'s text at ``rev`` for :func:`gold_view`: empty only when ``rev`` positively
    lacks the path (an added or deleted file), its blob is binary (a NUL byte, git's rule) or
    it is a submodule pointer; any other failed read raises :class:`GoldReadError`."""
    try:
        text = repo.show_file(rev, path)
    except UnicodeDecodeError as err:
        try:
            blob = repo.show_blob(rev, path)
        except Exception as inner:
            raise GoldReadError(f"{rev[:12]}:{path}") from inner
        if blob is not None and b"\0" in blob:
            return ""
        raise GoldReadError(f"{rev[:12]}:{path} is not UTF-8 text") from err
    except Exception as err:
        raise GoldReadError(f"{rev[:12]}:{path}") from err
    if text is not None:
        return text
    try:
        listed = repo.run("--literal-pathspecs", "ls-tree", "-z", rev, "--", path, raw=True)
    except Exception as err:
        raise GoldReadError(f"{rev[:12]}:{path}") from err
    if not listed.ok:
        raise GoldReadError(f"{rev[:12]}:{path}: {listed.stderr.strip()[:200]}")
    for record in listed.stdout.split("\0"):
        meta, _, name = record.partition("\t")
        if name == path:
            if meta.split(" ")[1:2] == ["commit"]:
                return ""
            raise GoldReadError(f"{rev[:12]}:{path} is in the tree but unreadable")
    return ""


#: More candidates than this and the parent-tree read is skipped: every candidate stays
#: novel (the guard fails closed rather than build an unbounded command line).
MAX_CANDIDATES = 2000
#: How many ``git grep -o`` passes :func:`_absent_from_parent` makes. ``-o`` prints one match
#: per position (the longest), so a candidate inside a longer candidate's match is only seen
#: on a later pass without that longer one. Past this many passes the rest stay novel.
MAX_GREP_PASSES = 8


def novel_tokens(
    repo: GitRepo, *, parent: str, commit: str, paths: Sequence[str]
) -> frozenset[str]:
    """The identifiers and literals the commit introduced — present in the gold post-image
    of ``paths`` and absent from the WHOLE parent tree — computed harness-side, so the
    builder never sees the diff that powers the check (ADR-0026 item 7). One ``git grep``
    over the parent tree decides which candidates the parent already held."""
    candidates: set[str] = set()
    for path in paths:
        candidates |= _introduced(_show(repo, parent, path), _show(repo, commit, path))
    return _absent_from_parent(repo, parent, candidates)


def _introduced(before: str, after: str) -> set[str]:
    after_i, after_l = _code_tokens(after)
    before_i, before_l = _code_tokens(before)
    return (after_i - before_i) | (after_l - before_l)


def _absent_from_parent(repo: GitRepo, parent: str, candidates: set[str]) -> frozenset[str]:
    """The ``candidates`` the WHOLE parent tree lacks as whole words: the same answer as
    ``git grep -q -w -F`` per candidate (``GoldView.parent_has``), in few ``git grep`` runs,
    except that a word the parent holds only in a binary file stays novel (``-I``; fail
    closed, as the single read always did).

    ``git grep -o`` prints only the longest match at a position and resumes after it, so a
    candidate the parent holds only inside a longer candidate's match ("Service" inside the
    literal "Service Unavailable") is not printed. Every printed line that equals a remaining
    candidate is one the parent holds; drop those and grep again for the rest, until a pass
    sees nothing new. A printed line is only ever an exact pattern found as a whole word, so a
    pass can drop a held token but never an absent one; past :data:`MAX_GREP_PASSES`, or on
    any failure, the rest stay novel (fail closed)."""
    if not candidates:
        return frozenset()
    if len(candidates) > MAX_CANDIDATES:
        return frozenset(candidates)
    remaining = set(candidates)
    for _ in range(MAX_GREP_PASSES):
        if not remaining:
            break
        try:
            found = repo.run(
                "grep",
                "-I",
                "-h",
                "-o",
                "-w",
                "-F",
                *[a for tok in sorted(remaining) for a in ("-e", tok)],
                parent,
                check=False,
            ).stdout
        except Exception:  # cannot read the parent tree: the rest stay novel (fail closed)
            break
        # exact lines only, never stripped: a line that is not itself a remaining candidate
        # (a "Binary file ... matches" notice) proves nothing
        seen = set((found or "").split("\n")) & remaining
        if not seen:
            break
        remaining -= seen
    return frozenset(remaining)


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


# --- the stated-requirement guard (ADR-0052) ----------------------------------------------


@dataclass(frozen=True)
class GoldView:
    """What :func:`req_guard` reads of the gold change, harness-side (the builder never sees
    it): the novel tokens, the source and test post-images, the lines the change added to
    each, the held-out test paths, and ``parent_has`` — whether the parent tree holds a
    token as a whole word, case-sensitively (``git grep -w -F``, the matcher
    :func:`novel_tokens` uses; any failure answers ``False``, so a token stays answer-side).
    ``test_after_by_path`` holds each test path's own post-image (``(path, text)``), so a
    language-specific rule reads only its own language's files; left empty, ``test_after``
    stands for it when every test path is one language's. ``product_has`` is the stricter
    question the ``product`` provenance asks: whether the parent holds the token that way in
    a file that is not a test file, on a line that is not only a comment; ``None`` reads
    ``parent_has``. ``parent_has_run`` asks whether the parent holds a run of words in order,
    case-insensitively, with only non-alphanumeric characters or a format verb or placeholder
    (:data:`_RUN_GAP_ERE`) between them; ``None`` asks ``parent_has`` for the words joined by
    single spaces."""

    novel: frozenset[str]
    parent_has: Callable[[str], bool]
    src_after: str = ""
    test_after: str = ""
    src_added: tuple[str, ...] = ()
    test_added: tuple[str, ...] = ()
    test_paths: tuple[str, ...] = ()
    test_after_by_path: tuple[tuple[str, str], ...] = ()
    product_has: Callable[[str], bool] | None = None
    parent_has_run: Callable[[Sequence[str]], bool] | None = None


#: A line that is only a comment (``//``, ``#``, ``/*``, a ``*`` continuation, ``--``): a word
#: on it is not product code. Its errors go answer-side only: a trailing comment after code is
#: not caught (the word stays ``product``), and a code line starting ``*`` or ``#`` reads as a
#: comment (the word ranks by the change instead).
_COMMENT_LINE_RE = re.compile(r"^\s*(?://|#|/\*|\*|--)")


def _added_lines(before: str, after: str) -> list[str]:
    out: list[str] = []
    sm = difflib.SequenceMatcher(None, before.splitlines(), after.splitlines(), autojunk=False)
    after_lines = after.splitlines()
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(after_lines[j1:j2])
    return out


#: What may stand between two words of a parent run (``parent_has_run``, a POSIX ERE): any
#: non-alphanumeric character or a :data:`_FORMAT_VERB_RE` format verb or placeholder (a plain
#: group: ``git grep -E`` has no ``(?:``).
_RUN_GAP_ERE = r"([^A-Za-z0-9]|%[-+#0-9.*]*[A-Za-z%]|\{[A-Za-z0-9_:.!]*\})+"


def gold_view(
    repo: GitRepo,
    *,
    parent: str,
    commit: str,
    src_paths: Sequence[str],
    test_paths: Sequence[str],
    novel: frozenset[str] | None = None,
) -> GoldView | None:
    """The :class:`GoldView` of one task's change, read harness-side through ``repo``; ``None``
    (no gold view, so :func:`req_guard` withholds the entry) when a blob the commit or its
    parent holds cannot be read — a path either side lacks reads empty. ``novel``, when
    given, is completed from the view's own reads (the union), never trusted short."""
    candidates: set[str] = set()

    def read(paths: Sequence[str]) -> tuple[list[str], list[str]]:
        afters: list[str] = []
        added: list[str] = []
        for path in paths:
            after = _show_strict(repo, commit, path)
            before = _show_strict(repo, parent, path)
            afters.append(after)
            added.extend(_added_lines(before, after))
            candidates.update(_introduced(before, after))
        return afters, added

    try:
        src_afters, src_added = read(src_paths)
        test_afters, test_added = read(test_paths)
    except GoldReadError:
        return None

    def parent_has(token: str) -> bool:
        try:
            return repo.run("grep", "-q", "-w", "-F", "-e", token, parent, check=False).ok
        except Exception:
            return False

    def product_has(token: str) -> bool:
        try:
            out = repo.run(
                "grep", "-I", "-z", "-w", "-F", "-e", token, parent, check=False, raw=True
            )
        except Exception:
            return False
        prefix = f"{parent}:"
        held_out = frozenset(test_paths)  # a supplied test file is never product evidence
        # one record per "\n" ("rev:path\0line"); never str.splitlines, which also splits on
        # form feeds and other separators inside a source line and could fake a hit
        for rec in (out.stdout or "").split("\n"):
            name, sep, line = rec.partition("\0")
            if not sep or not name.startswith(prefix):
                continue
            path = name[len(prefix) :]
            if path not in held_out and not is_test_path(path) and not _COMMENT_LINE_RE.match(line):
                return True
        return False

    def parent_has_run(run: Sequence[str]) -> bool:
        # the words are [a-z0-9]+ (``_literal_words``), so the pattern needs no escaping; a
        # format verb between them is skipped as ``_literal_words`` drops it on the other side
        pattern = _RUN_GAP_ERE.join(run)
        try:
            return repo.run("grep", "-q", "-I", "-i", "-w", "-E", "-e", pattern, parent).ok
        except Exception:
            return False

    known = frozenset() if novel is None else novel
    novel = known | _absent_from_parent(repo, parent, candidates - known)
    return GoldView(
        novel=novel,
        parent_has=parent_has,
        product_has=product_has,
        parent_has_run=parent_has_run,
        src_after="\n".join(src_afters),
        test_after="\n".join(test_afters),
        src_added=tuple(src_added),
        test_added=tuple(test_added),
        test_paths=tuple(test_paths),
        test_after_by_path=tuple(zip(test_paths, test_afters, strict=True)),
    )


#: A test-definition line: the names and descriptions on it are the held-out tests' own.
_TEST_DEF_RE = re.compile(
    r"^\s*(?:"
    r"(?:async\s+)?def\s+test\w*|class\s+Test\w*|func\s+(?:Test|Benchmark|Example|Fuzz)\w*"
    r"|fn\s+\w+|#\[test\]|#\[cfg\(test\)\]|mod\s+tests\b"
    r"|(?:it|test|describe|context)(?:\.\w+)?\s*\(|t\.Run\s*\(|@Test\b|@DisplayName\b"
    r"|@pytest\.mark\.parametrize\b|@ParameterizedTest\b"
    r")"
)
#: Any definition line of a test file: the name it defines (a helper, a fixture, a constant)
#: belongs to the held-out tests unless the source or the parent holds it too.
_DEF_NAME_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
    r"(?:def|function\*?|func|fn|class|const|let|var)\s+(?:\([^)]*\)\s*)?"
    r"([A-Za-z_$][A-Za-z0-9_$]*)"
)
#: A Python assignment of a Python test file (``LIMIT = 10``, ``LIMIT: int = 10``, ``A, B = 1, 2``,
#: ``self.LIMIT = 10``, each target of ``A = B = 1``): every name it binds is a held-out name
#: too. ``==`` is a comparison, not a definition.
_PY_TARGET = r"(?:(?:self|cls)\.)?[A-Za-z_][A-Za-z0-9_]*"
_PY_ASSIGN_RE = re.compile(
    rf"\s*\(?\s*((?:{_PY_TARGET}\s*,\s*)*{_PY_TARGET})\s*,?\s*\)?\s*(?::[^=\n]*)?=(?!=)"
)
_PY_RECEIVERS = frozenset({"self", "cls"})
_PY_SUFFIXES = (".py", ".pyi")
#: A method or class declaration of a JVM or .NET test file, after any block comment,
#: annotations or attributes on the same line (``@Test void x()``, ``[Fact] public async
#: Task X()``, ``public <T extends C<T>> T x(``, ``void X<T>(``, ``def x[T](``, Kotlin
#: ``fun x(``, ``fun Foo.x(`` and ``fun `does x`(``, Spock ``def "does x"(``, ``@Nested
#: class X``, C# ``record class X`` and ``record struct X``): the name it declares is a held-out
#: name, so a method declared on the line after ``@Test`` is one too. Only those files are read
#: so (a Go or Python test is not).
_JVM_SUFFIXES = (".java", ".kt", ".kts", ".scala", ".groovy", ".cs")
_JVM_STR = r'"(?:[^"\\]|\\.)*"'
_JVM_ARGS = rf"\((?:{_JVM_STR}|[^()\"]|\([^()]*\))*\)"
_JVM_GENERIC = r"<(?:[^<>()]|<[^<>()]*>)*>"
_JVM_METHOD_RE = re.compile(
    r"^\s*(?:/\*(?:[^*]|\*(?!/))*\*/\s*)*"
    rf"(?:(?:@[\w.]+(?:\s*{_JVM_ARGS})?|\[(?:{_JVM_STR}|[^\]\"])*\])\s*)*"
    r"(?:(?:public|private|protected|internal|static|final|abstract|override|open|suspend"
    r"|async|virtual|sealed|synchronized|default|inline|operator|infix|native|strictfp"
    r"|unsafe|partial|extern|tailrec|external|inner|data|enum|annotation|value|implicit"
    r"|readonly)(?:\[[^\]]*\])?\s+)*"
    rf"(?:{_JVM_GENERIC}\s*)?"
    r"(?:(?:record\s+(?:class|struct)|class|interface|object|record|struct|enum|trait)\s+"
    r"(?P<cls>[A-Za-z_]\w*)"
    rf"|(?:fun\s+(?:{_JVM_GENERIC}\s*)?(?:\w+(?:{_JVM_GENERIC})?\??\.)*|def\s+"
    r"|(?P<type>[\w.]+(?:<[^()]*?>)?(?:\[\])*\??|\([^()]*\))\s+)"
    rf"(?P<name>[A-Za-z_]\w*|`[^`]+`|\"[^\"]+\")\s*(?:{_JVM_GENERIC}|\[[^\]]*\])?\s*\()"
)
#: Lower-case return types a declaration may name; any other plain lower-case word before
#: a call (``return f(``, ``println f(``, ``result shouldBe(``) starts a statement.
_JVM_PRIMITIVES = frozenset(
    {"void", "boolean", "byte", "char", "short", "int", "long", "float", "double", "string"}
    | {"bool", "object", "decimal", "dynamic", "sbyte", "uint", "ulong", "ushort", "nint"}
    | {"nuint"}
)


def _jvm_declared(line: str) -> str | None:
    """The method or class name a JVM or .NET declaration line declares (``None`` when it is
    not one); a Kotlin backtick or Spock string name is returned without its quotes."""
    m = _JVM_METHOD_RE.match(line)
    if not m:
        return None
    if m.group("cls"):
        return m.group("cls")
    kind = m.group("type") or ""
    if kind.isidentifier() and kind[0].islower() and kind not in _JVM_PRIMITIVES:
        return None
    return m.group("name").strip('`"')


def _py_assigned(line: str) -> list[str]:
    """Every name a Python assignment line binds (empty when it is not one)."""
    names: list[str] = []
    pos = 0
    while m := _PY_ASSIGN_RE.match(line, pos):
        names += [n for n in re.findall(r"[A-Za-z_]\w*", m.group(1)) if n not in _PY_RECEIVERS]
        pos = m.end()
    return names


#: English words dropped from both sides before the copy rule compares spans.
_SPAN_STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "as",
        "is",
        "are",
        "be",
        "it",
        "its",
        "this",
        "that",
        "at",
        "from",
        "not",
        "no",
        "when",
        "if",
        "then",
        "else",
        "must",
        "should",
        "will",
        "can",
        "may",
        "into",
        "than",
    ]
)
_SPAN_TOKEN_RE = re.compile(r"[a-z_][a-z0-9_]*|\d+")
_SIGNATURE_BODY = ("{", "}", ";", "=>")
_SIGNATURE_RETURN_RE = re.compile(r"\breturn\b")
#: Executable Python outside a signature item's parameter list (before its name, or past its
#: header): a call, an ``=`` (an assignment or a comparison), a
#: ``raise``/``yield``/``await``/``lambda``, a spaced arithmetic operator (``r ** 2``,
#: ``x * k``), a simple statement opening the text, or a compound statement's own ``if …:``
#: header. Prose (``raises``) stays.
_SIGNATURE_CODE_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_.]*\(|=|\b(?:raise|yield|await|lambda)\b|\*\*|\s(?://|[*/%+])\s"
    r"|^\s*(?:pass|assert|del|import|global|nonlocal|break|continue)\b"
    r"|^\s*(?:if|elif|else|for|while|with|try|except|finally)\b[^:]*:"
)
#: What a signature header may carry after its closing parenthesis: one return annotation
#: (``-> T``) and Python's closing ``:``. Anything after it is the item's remainder.
_SIGNATURE_TAIL_RE = re.compile(r"(?:\s*->\s*[\w.\[\]|,]+)?\s*:?")
#: A Go method: ``func`` and a receiver group, then only one plain name before the
#: parameter list (``func (x *T) Name(``); anything else there means no receiver.
_GO_METHOD_RE = re.compile(r"\s*func\s*\(")
_GO_METHOD_NAME_RE = re.compile(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*(?=\()")
#: What a Go method header may carry after its parameter list: one result, a bare type
#: (``bool``, ``*Context``, ``[]string``, ``map[string]int``) or one parenthesised list of
#: types (``(int, error)``) — never a brace, ``=``, a call or an operator; a name or group
#: an ``(`` follows is a call, so it stays in the remainder.
_GO_RESULT_RE = re.compile(r"(?:\s*(?:\([\w.*\[\], ]*\)|[\w.*\[\]]+)(?![\w.*\[\]]*\s*\())?")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _span_tokens(text: str) -> list[str]:
    return [t for t in _SPAN_TOKEN_RE.findall(text.lower()) if t not in _SPAN_STOPWORDS]


def _grams(tokens: Sequence[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _copied_span(text: str, gold_lines: Sequence[str], n: int) -> bool:
    """Whether ``text`` shares an ``n``-token run with ``gold_lines``, read on the gold's own
    token vocabulary: every word of ``text`` the gold lines do not hold is dropped first, so
    filler words inserted between copied tokens never break the run; and a run still counts
    when every token inserted inside it is a copy of one and the same gold-vocabulary token,
    the run's ``n`` tokens within ``2n`` consecutive tokens of what is left. Filler of two or
    more distinct gold-vocabulary tokens, or a run spread wider than ``2n``, is not found."""
    gold_seq = _span_tokens("\n".join(gold_lines))
    vocab = set(gold_seq)
    seq = [t for t in _span_tokens(text) if t in vocab]
    if _grams(seq, n) & _grams(gold_seq, n):
        return True
    by_first: dict[str, list[tuple[str, ...]]] = {}
    for gram in _grams(gold_seq, n):
        by_first.setdefault(gram[0], []).append(gram)
    for i, tok in enumerate(seq):
        window = seq[i : i + 2 * n]
        for gram in by_first.get(tok, ()):
            if any(_gapped(window, gram, filler) for filler in set(window)):
                return True
    return False


def _gapped(window: Sequence[str], gram: Sequence[str], filler: str) -> bool:
    """Whether ``gram`` starts ``window`` and runs on in order with only copies of
    ``filler`` skipped between its tokens (greedy: a token equal to the next gram token is
    always taken, which never loses a match when only one token may be skipped)."""
    j = 0
    for g in gram:
        while j < len(window) and window[j] != g and window[j] == filler:
            j += 1
        if j >= len(window) or window[j] != g:
            return False
        j += 1
    return True


def _names_ci(text: str, token: str) -> bool:
    """Whether ``text`` names ``token`` case- and whitespace-insensitively: an identifier as
    a whole word, anything else as a substring."""
    if token.isidentifier():
        return token.lower() in {w.lower() for w in _IDENT_RE.findall(text)}
    return _norm(token) in _norm(text)


def _holds(text: str, token: str) -> bool:
    """Whether ``text`` holds ``token`` as :func:`novel_tokens` reads the parent tree: as a
    whole word, case-sensitively (``git grep -w -F``)."""
    if token.isidentifier():
        return token in set(_IDENT_RE.findall(text))
    return re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", text) is not None


def _token_provenance(token: str, gold: GoldView) -> str:
    """The token's provenance. ``product`` first only when the parent holds it in product
    code (``product_has``); a token the parent holds only in a test file or a comment ranks
    by the change's post-images, and falls back to ``product`` (never lower than the parent
    rule alone) when neither post-image holds it. The label only ever moves answer-side."""
    product_has = gold.product_has if gold.product_has is not None else gold.parent_has
    if product_has(token):
        return _stated.PROV_PRODUCT
    if _holds(gold.src_after, token):
        return _stated.PROV_CHANGE_DETAIL
    if _holds(gold.test_after, token):
        return _stated.PROV_TESTS_ONLY
    if gold.parent_has(token):
        return _stated.PROV_PRODUCT
    return _stated.PROV_NOWHERE


def _change_tokens(gold: GoldView) -> set[str]:
    """Every code token (:func:`_code_tokens`) of the change's source and test post-images."""
    out: set[str] = set()
    for text in (gold.src_after, gold.test_after):
        idents, literals = _code_tokens(text)
        out |= idents | literals
    return out


def _test_text(gold: GoldView, suffixes: tuple[str, ...] = _PY_SUFFIXES) -> str:
    """The post-images of the test files ending in ``suffixes`` (default: Python) only: per
    path when the view carries them, else ``test_after`` when every test path ends so."""
    if gold.test_after_by_path:
        return "\n".join(t for p, t in gold.test_after_by_path if p.endswith(suffixes))
    if gold.test_paths and all(p.endswith(suffixes) for p in gold.test_paths):
        return gold.test_after
    return ""


def _test_def_tokens(gold: GoldView) -> set[str]:
    """The held-out tests' own names: every token of an added test-definition line, the
    name any definition line of a test post-image defines (a helper, fixture or constant),
    every name a Python assignment of a Python test file binds, and every method name a
    JVM or .NET test file declares (the one after ``@Test`` included)."""
    out: set[str] = set()
    for line in gold.test_added:
        if _TEST_DEF_RE.match(line):
            idents, literals = _code_tokens(line)
            out |= idents | literals
    names: list[str] = []
    for line in gold.test_after.splitlines():
        if m := _DEF_NAME_RE.match(line):
            names.append(m.group(1))
    for line in _test_text(gold).splitlines():
        if not _DEF_NAME_RE.match(line):
            names += _py_assigned(line)
    for line in _test_text(gold, _JVM_SUFFIXES).splitlines():
        if declared := _jvm_declared(line):
            names.append(declared)
    out.update(n for n in names if len(n) >= NOVEL_MIN)
    return out


def _close_paren(text: str, start: int) -> int:
    """The index of the parenthesis closing the ``(`` at ``start``; ``-1`` when unbalanced."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _signature_split(statement: str, *, go_method: bool = False) -> tuple[str, str]:
    """``(header, remainder)`` of a signature item: the header runs through the parenthesis
    closing the first ``(``, plus one return annotation and a closing ``:``; with no
    balanced parenthesis there is no header. Only the header is exempt from the source-span
    rule, which reads it so. With ``go_method`` (the body check), a Go method's header runs
    on through its parameter list and one result (:data:`_GO_RESULT_RE`) instead, so the
    receiver group is not mistaken for the whole header."""
    start = statement.find("(")
    if start < 0:
        return "", statement
    close = _close_paren(statement, start)
    if close < 0:
        return "", statement
    if go_method and _GO_METHOD_RE.match(statement):
        name = _GO_METHOD_NAME_RE.match(statement, close + 1)
        params_close = _close_paren(statement, name.end()) if name else -1
        if params_close >= 0:
            m = _GO_RESULT_RE.match(statement, params_close + 1)
            end = m.end() if m else params_close + 1
            return statement[:end], statement[end:]
    m = _SIGNATURE_TAIL_RE.match(statement, close + 1)
    end = m.end() if m else close + 1
    return statement[:end], statement[end:]


#: Test-file stems too generic to say which held-out test a text means.
_GENERIC_STEMS: frozenset[str] = frozenset(
    {"test", "tests", "spec", "specs", "index", "main", "init", "__init__", "conftest", "utils"}
)


def _names_test_path(text: str, gold: GoldView) -> bool:
    """Whether ``text`` names a held-out test's path or file name (as a substring) or its
    stem (as a whole word, a generic stem excepted)."""
    for path in gold.test_paths:
        base = path.rsplit("/", 1)[-1]
        stem = base.split(".", 1)[0]
        if _norm(path) in _norm(text) or _norm(base) in _norm(text):
            return True
        specific = len(stem) >= NOVEL_MIN and stem.lower() not in _GENERIC_STEMS
        if specific and _names_ci(text, stem):
            return True
    return False


#: A string literal of a test line: double-quoted, single-quoted or a Go raw string.
_LITERAL_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`([^`\n]*)`')
#: A format verb or placeholder (``%T``, ``%-5.2f``, ``%%``, ``{}``, ``{0}``, ``{name}``),
#: dropped before words are read on both sides, so ``writer %T does`` reads ``writer does``.
_FORMAT_VERB_RE = re.compile(r"%[-+#0-9.*]*[A-Za-z%]|\{[\w:.!]*\}")
_LITERAL_WORD_RE = re.compile(r"[a-z0-9]+")
#: What ends the text before a literal that names a test case rather than asserting a value:
#: a Go ``t.Run(`` or Python ``subTest(`` first argument.
_CASE_NAME_BEFORE_RE = re.compile(
    r"(?:\.Run\(|\bsubTest\((?:msg\s*=\s*)?)\s*$",
    re.IGNORECASE,
)
#: An ``id=`` keyword ending the text before a literal: a case name only when the call it
#: belongs to (:func:`_owning_call`) is a pytest ``param`` (:data:`_PARAM_CALL_RE`).
_ID_BEFORE_RE = re.compile(r"\bid\s*=\s*$")
_PARAM_CALL_RE = re.compile(r"(?:\bpytest\.|(?<![\w.]))param\s*$")
#: An ``ids=`` list or tuple opening: its literals are case names only when the call it
#: belongs to (:func:`_owning_call`) is a pytest ``parametrize`` (:data:`_PARAMETRIZE_CALL_RE`);
#: a plain ``ids = [...]`` assignment may hold the expected values.
_IDS_OPEN_RE = re.compile(r"\bids\s*=\s*[\[(]")
_PARAMETRIZE_CALL_RE = re.compile(r"\bparametrize\s*$")
#: The line breaks :mod:`ast` counts lines by, so a row of :func:`_docstring_rows` is a line
#: here. ``str.splitlines`` (which :func:`_added_lines` uses) also breaks on form feeds and
#: other separators, so :func:`_docstring_lines` compares the ``splitlines`` pieces of each row.
_AST_LINE_RE = re.compile(r"\r\n|\r|\n")
_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _in_ids_list(masked: str, start: int) -> bool:
    """Whether position ``start`` of ``masked`` (a line with literal contents blanked) lies
    inside a pytest ``parametrize(..., ids=[...])`` opened earlier on the same line."""
    opens = list(_IDS_OPEN_RE.finditer(masked, 0, start))
    if not opens:
        return False
    if _PARAMETRIZE_CALL_RE.search(_owning_call(masked, opens[-1].start())) is None:
        return False
    gap = masked[opens[-1].end() : start]
    return 1 + gap.count("[") + gap.count("(") - gap.count("]") - gap.count(")") > 0


def _owning_call(masked: str, start: int) -> str:
    """The text before the ``(`` still open at position ``start`` of ``masked`` (a line with
    literal contents blanked): the call an argument there belongs to; empty when none is open
    on the line."""
    depth = 0
    for i in range(start - 1, -1, -1):
        c = masked[i]
        if c in ")]}":
            depth += 1
        elif c in "([{":
            if depth == 0:
                return masked[:i] if c == "(" else ""
            depth -= 1
    return ""


def _docstring_rows(tree: ast.Module, lines: Sequence[str], others: set[str]) -> set[int]:
    """The 1-based rows of ``lines`` (the source ``tree`` parsed) that a module, class or
    function docstring fills whole — its first statement, an expression statement holding a
    string constant, nothing but whitespace before it on its first row or after it on its last
    — unless its text is also held by another string constant (``others``, the docstring-free
    string constants of every parsed post-image) or holds a doctest prompt (``>>>``), whose
    expected output is asserted under ``--doctest-modules``."""
    rows: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS) or not node.body:
            continue
        doc = node.body[0]
        if not (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
            and doc.end_lineno is not None
            and doc.end_col_offset is not None
            and doc.value.value not in others
            and ">>>" not in doc.value.value
        ):
            continue
        head = lines[doc.lineno - 1].encode()[: doc.col_offset]
        tail = lines[doc.end_lineno - 1].encode()[doc.end_col_offset :]
        if not head.strip() and not tail.strip():
            rows.update(range(doc.lineno, doc.end_lineno + 1))
    return rows


def _docstring_lines(gold: GoldView) -> frozenset[str]:
    """The test post-image lines that lie only inside docstrings (:func:`_docstring_rows`) of
    Python test files that parse: an added line among them is a docstring, never asserted.
    A line any other row of any test post-image also holds — a non-Python file, a Python file
    that does not parse, or a non-docstring row — is not among them (fails closed)."""
    if gold.test_after_by_path:
        posts = [(p.endswith(_PY_SUFFIXES), t) for p, t in gold.test_after_by_path]
    else:
        python = bool(gold.test_paths) and all(p.endswith(_PY_SUFFIXES) for p in gold.test_paths)
        posts = [(python, gold.test_after)]
    trees: list[ast.Module | None] = []
    docs: set[int] = set()  # the ids of docstring constants
    others: set[str] = set()
    for python, text in posts:
        try:
            tree = ast.parse(text) if python else None
        except (SyntaxError, ValueError, RecursionError):  # ValueError: a null byte
            tree = None
        trees.append(tree)
        nodes = list(ast.walk(tree)) if tree is not None else []
        for node in nodes:
            if isinstance(node, _DOC_OWNERS) and node.body and isinstance(node.body[0], ast.Expr):
                docs.add(id(node.body[0].value))
        for node in nodes:
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
            ):
                others.add(node.value)
    inside: set[str] = set()
    elsewhere: set[str] = set()
    for (_python, text), tree in zip(posts, trees, strict=True):
        lines = _AST_LINE_RE.split(text)
        rows = _docstring_rows(tree, lines, others) if tree is not None else set()
        for row, line in enumerate(lines, 1):
            # the pieces test_added holds (_added_lines splits with str.splitlines)
            (inside if row in rows else elsewhere).update(line.splitlines())
    return frozenset(inside - elsewhere)


def _asserted_literals(
    lines: Sequence[str], docstrings: frozenset[str] = frozenset()
) -> Iterator[str]:
    """The contents of the string literals on added test ``lines`` that may be asserted: every
    literal except a test case's name (:data:`_CASE_NAME_BEFORE_RE`, the ``ids=`` list of a
    pytest ``parametrize`` or the ``id=`` of a pytest ``param`` on the same line) and a line of
    ``docstrings`` (:func:`_docstring_lines`: a docstring in the parsed Python test post-image).
    Conservative: a literal the rule cannot place (any table field, ``name:`` included, since a
    row of an expected list looks the same; a wrapped call; an ``id=`` or ``ids=`` of any other
    call) counts."""
    for line in lines:
        if line in docstrings:
            continue
        found = list(_LITERAL_RE.finditer(line))
        masked = list(line)
        for m in found:
            masked[m.start() + 1 : m.end() - 1] = " " * (m.end() - m.start() - 2)
        flat = "".join(masked)
        for m in found:
            if (
                _CASE_NAME_BEFORE_RE.search(line, 0, m.start())
                or (
                    _ID_BEFORE_RE.search(line, 0, m.start()) is not None
                    and _PARAM_CALL_RE.search(_owning_call(flat, m.start())) is not None
                )
                or _in_ids_list(flat, m.start())
            ):
                continue
            yield next(g for g in m.groups() if g is not None)


def _literal_words(text: str) -> list[str]:
    """``text``'s words for the asserted-literal rule: lower-case alphanumeric runs, with
    format verbs dropped (so case, whitespace and punctuation never break a run)."""
    return _LITERAL_WORD_RE.findall(_FORMAT_VERB_RE.sub(" ", text).lower())


def _asserted_literal(statement: str, gold: GoldView, request: str) -> bool:
    """Whether ``statement`` repeats :data:`~crb.core.stated.LITERAL_RUN_WORDS` words in a
    row of a string literal an added held-out test line may assert (:func:`_asserted_literals`;
    a whole literal of that many words or more included) that neither ``request`` nor the
    parent tree holds as a run."""
    n = _stated.LITERAL_RUN_WORDS
    said = _grams(_literal_words(statement), n)
    if not said:
        return False
    asked = _grams(_literal_words(request), n)
    has_run = gold.parent_has_run or (lambda run: gold.parent_has(" ".join(run)))
    runs: set[tuple[str, ...]] = set()
    for literal in _asserted_literals(gold.test_added, _docstring_lines(gold)):
        runs |= _grams(_literal_words(literal), n)
    return any(not has_run(run) for run in sorted((runs & said) - asked))


def req_guard(
    text: str,
    items: Sequence[_stated.StatedItem],
    structure: str,
    gold: GoldView | None,
    request: str = "",
) -> list[str]:
    """The reasons a stated-requirement entry is withheld (ADR-0052 item 3), sorted; empty
    when it may reach the brief. Fails closed: no ``gold`` view is ``req_no_gold``.

    ``req_render``: ``text`` is not ``structure``'s rendering of ``items``. ``req_length``:
    a fixed limit is broken. ``req_code_block``: a fence or an indented line.
    ``req_disclose``: a disclosed string is not exactly one token — a novel token, a code
    token of the change's post-images, or a whole word the parent holds.
    ``req_undeclared_novel``: an item's statement names a novel token its ``discloses`` does
    not declare exactly (a novel word inside a declared token's own text is covered by it;
    a declared token is masked only as a whole token, and a token named once it is masked as
    a plain substring counts too). ``req_provenance``: an item's declared provenance is not the most
    answer-side of its tokens' (each novel token its statement names, and each disclosed
    token). ``req_test_name``: the text names a held-out test's own name (a token of an
    added test-definition line, or a name a test file defines) that neither the source
    post-image nor the parent holds. ``req_test_path``: the text names a held-out test's
    path, file name or stem. ``req_test_span``: the entry's statements, read together in
    order on the change's token vocabulary, share an eight-token run with the change's added
    test lines (or, past a signature item's header, its added source lines), the run's tokens
    within sixteen with only copies of one token inserted inside it. ``req_signature``: a
    signature item carries a body (a brace, ``;``, ``=>``, ``return``, or executable Python
    before its name or past its header; a Go method's header runs through its parameter
    list and one result). ``req_asserted_literal``: an item's statement repeats four words in
    a row of a string literal an added held-out test line may assert (a case name, ``t.Run``
    or ``subTest`` title, pytest id or a docstring of a parsed Python test post-image aside;
    format verbs dropped, case,
    whitespace and punctuation ignored) that neither ``request`` — the text the builder is
    given — nor the parent tree holds; the author restates it in their own words."""
    if gold is None:
        return [_stated.REASON_NO_GOLD]
    reasons: set[str] = set()
    try:
        rendered = _stated.render(structure, items)
    except ValueError:
        rendered = None
    if rendered != text:
        reasons.add(_stated.REASON_RENDER)
    if _stated.length_violation(items, text):
        reasons.add(_stated.REASON_LENGTH)
    reasons.update(_text_guard(text, gold, prefix="req"))
    change = _change_tokens(gold)
    for item in items:
        valid = [d for d in item.discloses if d in gold.novel or d in change or gold.parent_has(d)]
        if len(valid) != len(item.discloses):
            reasons.add(_stated.REASON_DISCLOSE)
        declared = {_norm(d) for d in valid}
        # a declared token's own text is spent: a novel word inside it (``required`` in the
        # literal ``name required``) is covered; one anywhere else must be declared itself
        # only as a whole token (``load`` never masks the inside of ``payload``); the text
        # masked as a plain substring is read too (``t`` spent inside ``strip`` leaves ``s``),
        # so the guard never names fewer tokens than that reading did
        rest = _norm(item.statement)
        spent = rest
        for d in sorted(declared, key=len, reverse=True):
            rest = re.sub(r"(?<!\w)" + re.escape(d) + r"(?!\w)", " | ", rest)
            spent = spent.replace(d, " | ")
        named = [tok for tok in gold.novel if _names_ci(rest, tok)]
        named_spent = [tok for tok in gold.novel if _names_ci(spent, tok)]
        if any(_norm(tok) not in declared for tok in (*named, *named_spent)):
            reasons.add(_stated.REASON_UNDECLARED_NOVEL)
        if item.discloses:
            for toks in ({*valid, *named, *named_spent}, {*valid, *named_spent}):
                actual = max(
                    (_token_provenance(t, gold) for t in toks),
                    key=lambda p: _stated.PROV_RANK[p],
                    default=_stated.PROV_NOWHERE,
                )
                if actual != item.provenance:
                    reasons.add(_stated.REASON_PROVENANCE)
        if item.kind == _stated.KIND_SIGNATURE and (
            any(c in item.statement for c in _SIGNATURE_BODY)
            or _SIGNATURE_RETURN_RE.search(item.statement)
            or _SIGNATURE_CODE_RE.search(_signature_split(item.statement, go_method=True)[1])
            or _SIGNATURE_CODE_RE.search(item.statement.split("(", 1)[0])
        ):
            reasons.add(_stated.REASON_SIGNATURE)
        if _asserted_literal(item.statement, gold, request):
            reasons.add(_stated.REASON_ASSERTED_LITERAL)
    n = _stated.SPAN_TOKENS
    ordered = sorted(items, key=lambda i: i.item_id)
    whole = " ".join(i.statement for i in ordered)
    past_headers = " ".join(
        _signature_split(i.statement)[1] if i.kind == _stated.KIND_SIGNATURE else i.statement
        for i in ordered
    )
    if _copied_span(whole, gold.test_added, n) or _copied_span(past_headers, gold.src_added, n):
        reasons.add(_stated.REASON_TEST_SPAN)
    return sorted(reasons)


def _text_guard(text: str, gold: GoldView, *, prefix: str) -> set[str]:
    """The text-level checks :func:`req_guard` and :func:`plan_guard` share, each reason named
    ``<prefix>_<check>``: ``code_block`` (a fence, or a line indented four spaces or a tab),
    ``test_name`` (the text names a held-out test's own name that neither the source
    post-image nor the parent holds) and ``test_path`` (it names a held-out test's path, file
    name or stem)."""
    reasons: set[str] = set()
    if (
        "```" in text
        or "~~~" in text
        or any(ln.startswith(("    ", "\t")) for ln in text.splitlines())
    ):
        reasons.add(f"{prefix}_code_block")
    for tok in _test_def_tokens(gold):
        if _names_ci(text, tok) and not _holds(gold.src_after, tok) and not gold.parent_has(tok):
            reasons.add(f"{prefix}_test_name")
            break
    if _names_test_path(text, gold):
        reasons.add(f"{prefix}_test_path")
    return reasons


# --- the accepted-plan guard (ADR-0054) ---------------------------------------------------

#: The fewest characters (whitespace dropped) an added line, or its body past one leading
#: bare word, must hold for ``plan_gold_line`` to look for it in a plan.
GOLD_LINE_MIN = 10
#: A gold line ``plan_gold_line`` looks for holds at least one of these: it reads as code,
#: not prose (prose copies are the span rules' job).
_GOLD_LINE_CODE_CHARS = frozenset("()[]{}=<>")
#: One leading bare word of an added line (``assert``, ``return``, ``expect``, ``const``…):
#: the line's body past it is looked for too, so ``check clamp(5) == 3`` copies
#: ``assert clamp(5) == 3``.
_GOLD_LINE_LEAD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s+")
#: An operator or bracket: an executable whole line (:func:`_executable_line`) holds one
#: outside its string literals.
_EXEC_OP_CHARS = frozenset("()[]{}=<>+-*/%!&|^~.?@:")
#: A directive lead (``#define``, ``#include``): ``#`` touching a word is the line's operator.
_EXEC_DIRECTIVE_RE = re.compile(r"^#\w")
#: Statement keywords that, followed by one identifier, make a whole line that carries an
#: answer (``raise ValueError``, ``return total``, ``yield item``); written lower-case, so a
#: docstring's ``Return value`` stays prose.
_EXEC_LEAD_WORDS = frozenset(
    ["return", "yield", "raise", "throw", "await", "defer", "go", "del", "import"]
)
_EXEC_LEAD_PAIR_RE = re.compile(r"^([a-z]+)\s+([A-Za-z_][A-Za-z0-9_]*)$")
#: Keywords and bare literals that carry no answer on their own: an executable whole line
#: holds at least one word that is not one of these (lower-cased).
_TRIVIAL_WORDS = frozenset(
    [
        "return",
        "break",
        "continue",
        "pass",
        "else",
        "elif",
        "elsif",
        "if",
        "for",
        "while",
        "do",
        "then",
        "end",
        "fi",
        "done",
        "esac",
        "try",
        "catch",
        "except",
        "finally",
        "default",
        "case",
        "switch",
        "nil",
        "null",
        "none",
        "true",
        "false",
        "undefined",
        "self",
        "this",
        "super",
        "yield",
        "await",
        "async",
        "defer",
        "go",
        "new",
        "def",
        "func",
        "fn",
        "function",
        "class",
        "var",
        "let",
        "const",
        "val",
        "public",
        "private",
        "protected",
        "static",
        "void",
        "import",
        "from",
        "package",
        "raise",
        "throw",
        "throws",
        "assert",
        "del",
        "not",
        "and",
        "or",
        "in",
        "is",
        "with",
        "as",
        "endif",
    ]
)
_LINE_TOKEN_RE = re.compile(r"\w+|[^\w\s]")
_WORD_RE = re.compile(r"\w+")
_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}
#: The quotes that open a string literal for :func:`_scan_literals`.
_QUOTES = frozenset("'\"`")
#: A comment line for :func:`_executable_line` — its own test, not :data:`_COMMENT_LINE_RE`:
#: only a sure comment opener, ``//``, ``/*`` or ``*/``. A line led by ``*``, ``--`` or ``#``
#: may be code (``* p = 1``, ``--count``, ``#define N 4``, ``#[derive(Debug)]``), so it is
#: read like any other line: a short comment written that way that the plan quotes, lead
#: included, withholds it, as the fragment rule already does for a longer one.
_EXEC_COMMENT_RE = re.compile(r"^\s*(?://|/\*|\*/)")


def _squash(text: str) -> str:
    """``text`` lower-cased with all whitespace dropped."""
    return "".join(text.split()).lower()


def _line_tokens(text: str) -> tuple[str, ...]:
    """``text`` as lower-cased tokens: each run of word characters, and each other
    non-space character alone."""
    return tuple(_LINE_TOKEN_RE.findall(text.lower()))


def _holds_run(seq: Sequence[str], run: Sequence[str]) -> bool:
    """Whether ``run`` occurs contiguously in ``seq``."""
    n = len(run)
    if n == 0:
        return False
    first, rest = run[0], tuple(run[1:])
    return any(
        tok == first and tuple(seq[i + 1 : i + n]) == rest
        for i, tok in enumerate(seq[: len(seq) - n + 1])
    )


def _scan_literals(line: str) -> tuple[str, int, bool]:
    """``line`` read for string literals (``'``, ``"`` or a backtick, a backslash escaping
    the next character): the text outside them, how many closed, and whether the last one
    opened is left open."""
    outside: list[str] = []
    closed = 0
    quote = ""
    escaped = False
    for ch in line:
        if not quote:
            if ch in _QUOTES:
                quote = ch
                outside.append(" ")
            else:
                outside.append(ch)
        elif escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == quote:
            quote = ""
            closed += 1
    return "".join(outside), closed, bool(quote)


def _brackets_balance(text: str) -> bool:
    """Whether every ``()``, ``[]`` and ``{}`` in ``text`` opens and closes within it."""
    stack: list[str] = []
    for ch in text:
        if ch in "([{":
            stack.append(ch)
        elif ch in _BRACKET_PAIRS and (not stack or stack.pop() != _BRACKET_PAIRS[ch]):
            return False
    return not stack


def _balanced(line: str) -> bool:
    """Whether every ``()``, ``[]`` and ``{}`` outside a string literal in ``line`` opens and
    closes within it, so ``f(")")`` balances. A quote left open (an apostrophe, a Rust
    lifetime) may be no literal at all, so the line then balances when either reading does,
    counting every bracket or only those outside literals: an open quote never hides a
    copied line."""
    outside, _closed, left_open = _scan_literals(line)
    return _brackets_balance(outside) or (left_open and _brackets_balance(line))


def _executable_line(stripped: str) -> bool:
    """Whether a normalised added line (stripped, trailing ``;``, ``,``, ``:`` and ``{``
    dropped) is a complete executable line that carries an answer: not led by a sure comment
    opener (:data:`_EXEC_COMMENT_RE`: ``//``, ``/*``, ``*/``), its brackets balanced outside
    string literals (:func:`_balanced`), with a signal of code — an operator or bracket
    (:data:`_EXEC_OP_CHARS`) outside its string literals (anywhere when a quote is left open,
    which may be an apostrophe or a prime), a directive lead (:data:`_EXEC_DIRECTIVE_RE`), a
    closed string literal beside other text, or a statement keyword and one identifier
    (:data:`_EXEC_LEAD_WORDS`) — and a word, inside a literal or out, that is not a bare
    keyword or literal (:data:`_TRIVIAL_WORDS`). ``return g()``, ``return limit + 1``,
    ``f(")")``, ``*p = 1``, ``* p = 1``, ``#define N 4``, ``@Override``, ``raise ValueError``
    and ``return "ok"`` are; a blank line, ``}``, ``)``, ``else {``, ``return``,
    ``return nil``, ``return ""``, a bare ``"name"`` or ``"ok)"``, ``break``, a ``//`` or
    ``/*`` comment and a lone identifier are not."""
    if not stripped or _EXEC_COMMENT_RE.match(stripped) or not _balanced(stripped):
        return False
    outside, closed, left_open = _scan_literals(stripped)
    signal = (
        not _EXEC_OP_CHARS.isdisjoint(stripped if left_open else outside)
        or bool(_EXEC_DIRECTIVE_RE.match(stripped))
        or bool(closed and _WORD_RE.search(outside))
    )
    if not signal:
        pair = _EXEC_LEAD_PAIR_RE.match(stripped)
        signal = bool(pair and pair.group(1) in _EXEC_LEAD_WORDS)
    return signal and any(w.lower() not in _TRIVIAL_WORDS for w in _WORD_RE.findall(stripped))


def _gold_line(text: str, gold: GoldView, request: str) -> bool:
    """Whether ``text`` holds a line the change added to its source or tests, on either of
    two rules, each exempting a line ``request`` or the parent tree holds:

    1. A fragment — the whole line, or its body past one leading bare word
       (:data:`_GOLD_LINE_LEAD_RE`), with trailing ``;``, ``,``, ``:`` and ``{`` dropped —
       of at least :data:`GOLD_LINE_MIN` characters holding a code character
       (:data:`_GOLD_LINE_CODE_CHARS`), found case- and whitespace-insensitively.
    2. The whole line (normalised the same way) when it is executable
       (:func:`_executable_line`), however short: its token sequence (:func:`_line_tokens`)
       occurs contiguously in ``text``'s, so ``Use return g()`` holds ``return g()``, while
       ``x = 1`` is not found inside ``max = 10``.

    It catches the copy of a short change that the eight-token span rules cannot see: a
    one-line fix has fewer than eight tokens after stopwords."""
    said = _squash(text)
    asked = _squash(request)
    said_tokens = _line_tokens(text)
    asked_tokens = _line_tokens(request)
    for line in (*gold.src_added, *gold.test_added):
        stripped = line.strip().rstrip(";,:{").strip()
        if _executable_line(stripped):
            run = _line_tokens(stripped)
            if (
                _holds_run(said_tokens, run)
                and not _holds_run(asked_tokens, run)
                and not gold.parent_has(stripped)
            ):
                return True
        lead = _GOLD_LINE_LEAD_RE.match(stripped)
        for fragment in (stripped, stripped[lead.end() :] if lead else ""):
            squashed = _squash(fragment)
            if (
                len(squashed) >= GOLD_LINE_MIN
                and not _GOLD_LINE_CODE_CHARS.isdisjoint(squashed)
                and squashed in said
                and squashed not in asked
                and not gold.parent_has(fragment)
            ):
                return True
    return False


def plan_guard(
    plan: _plan.PlanBody,
    gold: GoldView | None,
    request: str = "",
    *,
    text: str | None = None,
) -> tuple[str, ...]:
    """The reasons an accepted-plan entry is withheld WHOLE (ADR-0054), sorted; empty when it
    may reach the brief. Fails closed: no ``gold`` view is ``plan_no_gold``.

    ``plan_render``: ``text`` (when given) is not the plan's rendering, or the plan breaks
    its shape. ``plan_length``: a fixed limit is broken. ``plan_code_block``,
    ``plan_test_name`` and ``plan_test_path``: :func:`_text_guard`'s checks, on the plan's
    own lines only — never the fixed header and headings the renderer adds, whose words a
    held-out test may share (the rendering adds no fence and no indentation, so the code-block
    check reads the same either way). ``plan_test_span``: the plan's lines, read together in
    order on the change's token vocabulary, share a :data:`~crb.core.stated.SPAN_TOKENS`-token
    run with the change's added test lines; ``plan_gold_span``: the same with its added source
    lines (a plan restates the change's code, which it was written without);
    ``plan_gold_line``: the plan's lines, read together, hold a whole added source or test
    line of code (:func:`_gold_line`), however few its tokens — a fragment of at least
    :data:`GOLD_LINE_MIN` characters with a code character, or any complete executable line
    (:func:`_executable_line`), however short. ``plan_asserted_literal``: the
    plan's lines, read together, repeat four words in a row of a string literal an added
    held-out test line may assert that neither ``request`` nor the parent holds. A token the
    change introduced that the plan names is NOT a reason: a plan written before the build may
    name what the build will add; :func:`plan_novel` counts it for the row."""
    if gold is None:
        return (_plan.REASON_NO_GOLD,)
    reasons: set[str] = set()
    try:
        rendered = _plan.render(plan)
    except ValueError:
        return (_plan.REASON_RENDER,)
    if text is not None and rendered != text:
        reasons.add(_plan.REASON_RENDER)
    if _plan.length_violation(plan, rendered):
        reasons.add(_plan.REASON_LENGTH)
    lines = plan.lines()
    reasons.update(_text_guard("\n".join(lines), gold, prefix="plan"))
    whole = " ".join(lines)
    n = _stated.SPAN_TOKENS
    if _copied_span(whole, gold.test_added, n):
        reasons.add(_plan.REASON_TEST_SPAN)
    if _copied_span(whole, gold.src_added, n):
        reasons.add(_plan.REASON_GOLD_SPAN)
    if _gold_line(whole, gold, request):
        reasons.add(_plan.REASON_GOLD_LINE)
    if _asserted_literal(whole, gold, request):
        reasons.add(_plan.REASON_ASSERTED_LITERAL)
    return tuple(sorted(reasons))


def plan_novel(text: str, gold: GoldView | None) -> int:
    """How many tokens the change introduced (``gold.novel``) ``text`` names, case- and
    whitespace-insensitively; ``0`` with no gold view. Counted on the row, never refused.
    The composer passes the kept plans' own lines, never the renderer's header and headings."""
    if gold is None:
        return 0
    return sum(1 for tok in gold.novel if _names_ci(text, tok))


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
    parent_rev: str = "",
    gold: GoldView | None = None,
) -> Composed:
    """THE brief composer (ADR-0026 items 1 and 7): the arm's brief for one ticket.

    ``facts`` and ``learned`` are context lines (structural facts; the loop's playbook lines,
    already held out and time-ordered); ``library`` the entries the arm carries. A
    retrospective brief admits a library entry only through :func:`admit_retrospective`,
    and refuses every bare fact (it carries no provenance to admit it by);
    every context line naming a ``novel`` token is refused and counted. A blind brief
    discloses no test (``BuildBrief`` refuses one that would). ``root`` — the worktree the
    brief is for — is kept out of the provenance hashes.

    On a context-set arm (ADR-0050 item 4) the admission comes from the arm, and the brief is
    always retrospective: a hindsight set (``ctx.oracle*``) skips the time rule only; a
    mechanical set (``ctx.mech*``) is admitted by :func:`admit_at_parent` against
    ``parent_rev`` (the task's parent commit, required); the leak guard and the bare-fact
    refusal apply to both, and the labels gain ``ctx_delivered`` and ``ctx_chars``.

    On a stated-requirement arm (``ctx.req*``, ADR-0052) an entry carrying items is checked by
    :func:`req_guard` against ``gold`` instead of the novel-token guard; a withheld entry is
    counted in ``ctx_refused`` and its reasons stamped as ``ctx_req_refused``. Every entry
    without items, every fact and every learned line keeps :func:`refuse_novel` there too.

    On an accepted-plan arm (``ctx.plan*``, ADR-0054) the entries are admitted at
    ``parent_rev`` without the mechanical stamp (:func:`admit_at_parent` with
    ``require_mechanical=False``); an entry carrying a plan is checked by :func:`plan_guard`
    instead of the novel-token guard and is withheld WHOLE on any reason (stamped as
    ``ctx_plan_refused``); a kept plan's text goes to ``BuildBrief.plan``, never to
    ``spec_facts``, and the gold-novel tokens it names are counted as ``ctx_plan_novel``."""
    ctx_name = _arms.ctx_set_name(arm)
    if ctx_name:
        retrospective = True
    admitted = list(library)
    lib_refused: list[str] = []
    bare_refused: list[str] = []
    if retrospective:
        if _arms.hindsight_arm(arm):
            # written with hindsight of the answer: never stamped mechanical, so the time
            # rule cannot admit it; it skips that rule ONLY (the guard below still runs)
            admitted, lib_refused = list(library), []
        elif ctx_name:
            if not parent_rev:
                raise ValueError(
                    f"a mechanical context-set arm ({arm}) is admitted at the task's parent "
                    "commit: compose needs parent_rev (ADR-0050 item 4)"
                )
            admitted, lib_refused = admit_at_parent(
                library, parent_rev, require_mechanical=not _arms.plan_arm(arm)
            )
        else:
            admitted, lib_refused = admit_retrospective(library, pool_began=pool_began)
        # a bare fact carries no provenance, so it cannot show it was produced mechanically
        # before the pool began: a retrospective brief takes facts only as library entries
        bare_refused, facts = list(facts), ()
    kept_facts, refused_facts = refuse_novel(facts, novel)
    kept_learned, refused_learned = refuse_novel(learned, novel)
    # ADR-0052 amends ADR-0050 items 3 and 4 for the req source ONLY: on a stated arm an
    # entry with items meets req_guard; everything else still meets refuse_novel
    stated = _arms.stated_arm(arm)
    planned = _arms.plan_arm(arm)
    req_entries = [e for e in admitted if stated and e.items]
    plan_entries = [e for e in admitted if planned and e.plan is not None]
    guarded = [e for e in admitted if e not in req_entries and e not in plan_entries]
    guard_texts, refused_lib = refuse_novel([e.text for e in guarded], novel)
    req_reasons: set[str] = set()
    req_kept: list[ContextEntry] = []
    for e in req_entries:
        why = req_guard(
            e.text, e.items, e.structure, gold, request=f"{ticket.subject}\n{ticket.message}"
        )
        if why:
            req_reasons.update(why)
            refused_lib.append(e.text)
        else:
            req_kept.append(e)
    # ADR-0054: a plan entry meets plan_guard and is withheld WHOLE on any reason
    request = f"{ticket.subject}\n{ticket.message}"
    plan_reasons: set[str] = set()
    plan_kept: list[ContextEntry] = []
    for e in plan_entries:
        withheld = plan_guard(e.plan, gold, request, text=e.text) if e.plan else ()
        if withheld:
            plan_reasons.update(withheld)
            refused_lib.append(e.text)
        else:
            plan_kept.append(e)
    kept_entries = tuple(
        e
        for e in admitted
        if e in req_kept or e in plan_kept or (e in guarded and e.text in guard_texts)
    )
    lib_texts = [e.text for e in kept_entries if e not in plan_kept]
    plan_text = "\n\n".join(e.text for e in plan_kept)
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
        plan=plan_text,
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
    if brief.plan:
        # only when there is one: every brief without a plan hashes exactly as before
        parts["plan"] = brief.plan
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
    if ctx_name:
        labels[LABEL_CTX_DELIVERED] = str(len(kept_entries))
        labels[LABEL_CTX_CHARS] = str(sum(len(e.text) for e in kept_entries))
    if req_reasons:
        labels[LABEL_CTX_REQ_REFUSED] = ",".join(sorted(req_reasons))
    if plan_reasons:
        labels[LABEL_CTX_PLAN_REFUSED] = ",".join(sorted(plan_reasons))
    if plan_kept:
        plan_lines = "\n".join(ln for e in plan_kept if e.plan for ln in e.plan.lines())
        labels[LABEL_CTX_PLAN_NOVEL] = str(plan_novel(plan_lines, gold))
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
    "LABEL_CTX_CHARS",
    "LABEL_CTX_DELIVERED",
    "LABEL_CTX_HARNESS",
    "LABEL_CTX_LIBRARY",
    "LABEL_CTX_PLAN_NOVEL",
    "LABEL_CTX_PLAN_REFUSED",
    "LABEL_CTX_REFUSED",
    "LABEL_CTX_REQ_REFUSED",
    "LABEL_CTX_RULES",
    "LABEL_CTX_TICKET",
    "MODIFIER_LOOP",
    "NOVEL_MIN",
    "TICKET_MESSAGE",
    "AuthorFn",
    "Composed",
    "ContextEntry",
    "GoldView",
    "S1Arm",
    "Ticket",
    "admit_at_parent",
    "admit_retrospective",
    "arm_base",
    "arm_carries_loop",
    "compose",
    "context_arm_for",
    "counts_as_s2_first_attempt",
    "gold_view",
    "names_novel",
    "novel_tokens",
    "plan_guard",
    "plan_novel",
    "refuse_novel",
    "req_guard",
]
