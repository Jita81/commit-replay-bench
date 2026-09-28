#!/usr/bin/env python3
"""The claim-tag gate — a quantified sentence on a public page carries its tag, or CI fails.

``docs/EVIDENCE-AND-CLAIMS.md`` §1 says every claim in this repository carries one tag:
``[measured]`` (with its ``n``, its method and the apparatus that produced it),
``[hypothesis]``, ``[aspiration]`` or ``[gap]``. Until this script that rule was prose, so
two claims on ``main`` were wrong for weeks and a reader found them, not a gate. This is the
gate: it reads the pages on ``ALLOWLIST``, finds the sentences that quantify something, and
fails when one carries no tag — or when a ``[measured]`` one does not carry what the tag
requires, or says its own rows are not in this repository (a reading nobody can re-derive
here is a ``[hypothesis]`` with that reason, DL-088).

    python scripts/claims_check.py            # report what is untagged
    python scripts/claims_check.py --check    # CI: exit non-zero on any finding

**The heuristic, honestly.** A sentence is treated as a claim when, after inline code, links
and HTML comments are stripped, it contains either a percentage (``95%``, ``95 per cent``,
``ninety percent``) or a cardinal (``12``, ``1200``, ``eleven``) qualifying a plural noun —
"eleven jobs", "22 tasks", "1200 tasks", "four public libraries". A tag covers the block it
sits in (a paragraph, a list item, a blockquote paragraph), and a list item is also covered
by the paragraph that introduces the list, which is how the README tags a whole measured
section at its head. Inline code is
stripped from the cover too: a page that *documents* ``[hypothesis]`` in backticks has not
thereby tagged the sentence around it.

**What it deliberately does not catch**, so nobody reads a green job as more than it is:

- *unquantified* claims — "the fastest", "secure by design", "proves correctness" — which are
  exactly the claims §7 forbids; a reader still has to read;
- claims inside tables, headings, fenced code, checklist items and a sentence that ends in a
  colon to introduce the thing it counts (the list below it is its own evidence); and what a
  reader never sees as prose: an HTML comment (a file's Navigation header — text after its
  closing ``-->`` on the same line is rendered, so it is read), a page's front matter, and,
  on a contents line only, the text of a link to a heading on the same page;
- a gap register line, where ``dod_check`` reads one — ``- **G-nnn** — what is missing ·
  what closes it · owner`` under ``## Gaps`` on a definition-of-done page or in
  docs/PREVENTION.md — is taken as its own ``[gap]`` tag: its form names what is absent and
  what would close it, which is what the tag must cite (a ``[measured]`` figure inside one
  still owes its n, method and apparatus); the same line anywhere else is prose. A sentence
  under a heading that lists what must never be said is quoted in order to forbid it, not
  claimed;
- a percentage that is itself the confidence level ("Wilson 95% interval", "95% CI") — a
  result standing beside one ("65% passed (Wilson 95% interval)") *is* caught — a four-digit
  year, and a number written with a leading zero, which is an identifier ("ADR-0011"), or
  written after ``§``, ``#``, a lettered prefix and a hyphen ("§9", "PR #48", "G-674") or a
  noun on ``NAMING_NOUNS`` that names one member of a numbered series ("belt 3", "stage 3",
  "item 11") — and only where it reads as a noun: capitalised, at the start of a sentence,
  or after a determiner, a preposition or an identifier ("at stage 3"), never after a
  subject or a modal ("the worker can batch 40 jobs"). A word that is mostly a verb or a
  gerund ("pass", "finding") is not on the list, and the list is pinned by a test beside
  the evasions every exemption must still refuse (P-240);
- whether the tag is the *right* one, and whether a ``[measured]`` figure is true: it checks
  that ``n``, a method and an apparatus version are *present*, never that they are sound.
  Only a person reading the ledger can do that;
- any file not on ``ALLOWLIST``: the decision records under ``docs/adr/`` and CHANGELOG are
  ungated (G-945), and the generated CODE-MAP and GAP-ANALYSIS are left to their generators'
  own ``--check`` (``UNGATED``).

**A review's actions are records, not prose.** A review under ``docs/reviews/`` that ends in
an *Actions* table (a heading containing "Actions", then rows whose first cell is a number)
sets work that must not disappear: every numbered action needs a line in
``docs/DECISION-LOG.md`` that starts a run of records with the review's file stem in
backticks and then states each action and its state —
```` `2026-09-13-critical-friend` action #1: closed …; action #8: [gap] … ```` — where the
state is the whole word ``closed``, ``open``, ``declined`` or ``[gap]``. The gate reads both
ways: a review action with no record fails, and so does a record whose review no longer
lists that action (a deleted row, a renamed *Actions* heading, a deleted review file), so
neither side can vanish alone. A fenced example inside the section is not an action. A
review in a folder under ``docs/reviews/`` is read too, and two reviews may not share a
file stem, because the record names its review by stem. The check reads the record's
*shape*, not whether the state is true; a person still reads the log.
Two of the critical friend's ten actions (#8, an independent human review of the core; #9,
rotating a pasted token) sat for twelve days with no record at all, which is what this rule
stops.

**A capability is stated only once it is built.** ``PROMISES`` registers capabilities a
page may state in the present tense only once the criterion that builds them is ``met`` in
``docs/dod/``: a matching sentence on a ``PROMISE_PAGES`` page (the allowlist and
EVIDENCE-AND-CLAIMS) is refused until then, and a promise whose criterion no longer exists is
refused too. The README once said the product names which ISO/IEC 25010 characteristics its
checks evidence while the criterion that builds that table was unmet (P-235). It holds only
the promises registered here; an unregistered capability sentence still needs a reader
(G-935).

**README's measured claims name their rows.** A ``[measured]`` tag on README (``ROWS_PAGES``),
wherever it renders — a paragraph, a list item, a heading, a table cell or a checklist item
(P-246) — must say where its rows are — ``rows: data/<campaign>/``, written plain inside the
tag — and that directory must be in the repository with a ``MANIFEST.sha256`` that verifies: every
listed file present and unchanged, and no file beside it that the manifest does not list
(its README excepted). The gate holds that shape; ``tests/test_measured_claims.py``
re-derives the numbers and the apparatus from the rows (G-660).

**A standard is named, never claimed.** The product names which ISO/IEC 25010
characteristics its checks evidence part of (``crb.core.quality_model``, EVIDENCE-AND-CLAIMS
§9) and never that code conforms to one. A sentence that says code conforms to, complies with
or is certified against an ISO standard (``ISO``, in any case, with or without a space before
its number) is refused on README, on the guides (the ones the UI bundles, read from
``DOC_NAMES`` in ``ui/src/help/docs.ts``, and every other page directly under ``docs/``) and
in the factory's pull-request body template (the string literals of ``pr_body`` and
``rework_comment``, of the module's functions they call and of the module constants they
read, each f-string or ``+`` join rendered with the constants it interpolates, imported ones
from ``crb`` included, and a value it cannot resolve read as a standard). It reads every
shape a page renders — headings, table cells and checklist items as well as prose (P-246). A
sentence that only names a standard passes, and so does one that denies the claim: a
negation in front of the conformity verb ("does not conform", "is not ISO/IEC 25010
compliant"), a negated verb whose complement carries it in the same clause ("does not mean
the code complies"), a refusal of a saying in the same clause ("the gate refuses a sentence
that says code conforms"), or a sentence in a section listing what must never be said
(EVIDENCE-AND-CLAIMS §7 quotes it to forbid it); a conformity word coordinated with a denied
one shares its denial ("conforms to, complies with or is certified against"). Nothing else
denies: "no doubt", "without exception", "not only conforms", or a refusal or negation in
another clause, and ``CONFORMITY_EVASIONS`` in the tests holds the cases (P-240, P-245). It
reads words, not meaning: "our pipeline is ISO-aligned" passes, and a reader still has to
read.

**How a file opts in.** Add its repository-relative path, or a glob for its folder, to
``ALLOWLIST`` below and make it pass in the same change. The list only grows: a page that
has been cleaned never leaves it, because leaving is how a gate quietly stops gating.

Navigation
----------
What it is:   The claim-tag gate over the public pages (CI's ``claims`` job; needs only the
              stdlib and markdown-it-py, which reads where a fenced code block ends).
What it does: Parses each allowlisted Markdown page into blocks, finds quantified sentences,
              and reports any that carry no permitted tag — and any ``[measured]`` tag
              without an n, a method or an apparatus version, or that says its rows are not
              in this repository (DL-088); reports every numbered action
              in a review's Actions table that has no stated record in the decision log,
              and every record whose review no longer lists the action or is no longer on
              disk; reports a registered promise stated in the present tense before its
              criterion is met (P-235); reports a sentence that claims ISO conformity on
              README, a guide or the factory's pull-request body template, in any shape the
              page renders (ADR-0026 item 11, P-245, P-246); reports a README
              ``[measured]`` tag that names no vendored rows, or rows
              whose checksum manifest does not verify (G-660); reports README's routing bar
              when it differs from ``RoutingPolicy.describe()`` (ADR-0025 item 10, P-311);
              --check exits non-zero.
How:          Split the page into blocks (skipping headings, tables, fenced code) → keep the
              paragraph that introduces a list as the item's cover → strip code, links and
              comments → split into sentences → test each for a percentage or a cardinal
              qualifying a plural noun → look for a permitted tag in the block's cover. Then
              each docs/reviews/**/*.md Actions table (fenced examples skipped) and each review
              the log names → its action numbers ⇄ the records in
              docs/DECISION-LOG.md, each under a head that names the review's stem in
              backticks, then ``action #N: <state>``. Then each ``PROMISES`` pattern over the
              sentences of ``PROMISE_PAGES`` ⇄ its criterion's state in docs/dod/. Then
              each sentence of README, the guides (every rendered shape) and the
              pull-request body's literals (``ast``, interpolations resolved) → an ISO
              mention and a conformity word that no verb in its clause denies. Then each
              README ``[measured]`` tag, in any rendered shape → its ``rows:`` locator →
              the manifest's hashes.
              Then README's text between the ``routing-bar`` markers, whitespace joined ⇄
              the code's ``RoutingPolicy.describe()`` (src/ on the path; the core is stdlib
              only).
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         docs/adr/0026-the-context-standard.md (item 11, the conformity rule),
              docs/adr/0025-routing-v2.md (item 10: the published bar is generated)
Works with:   docs/EVIDENCE-AND-CLAIMS.md (the claim-tag rule it enforces the shape of; §9,
              the quality baseline), src/crb/core/quality_model.py (the table a page may
              name), src/crb/core/routing.py (``RoutingPolicy.describe`` — the bar README
              carries), ui/src/help/docs.ts (the bundled guides), src/crb/factory/delivery.py
              (the pull-request body template), data/ (the vendored rows a README
              ``[measured]`` tag names), tests/test_measured_claims.py (re-derives them),
              README.md, docs/*.md, docs/reviews/ and docs/dod/ (the pages on
              ``ALLOWLIST``),
              docs/DECISION-LOG.md (where a review action's record lives),
              docs/dod/ (a promise's criterion and its state),
              docs/reviews/2026-09-13-critical-friend.md (the review whose actions it holds),
              .github/workflows/ci.yml (the claims job that runs --check),
              scripts/code_map.py (the same gate idiom: parse, validate, --check)
Tested by:    tests/test_claims_check.py
Touch when:   never for a new repository; a tag is added to the policy (update TAGS and
              EVIDENCE-AND-CLAIMS §1 together); a page joins the allowlist (add it and make it pass
              in the same change).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent.parent

#: The pages this gate reads: README, every guide under docs/, every review and every
#: definition-of-done page (a glob reads a page added later the day it lands). It only grows
#: (see the module docstring). The decision records and CHANGELOG are not on it yet (G-945).
ALLOWLIST: tuple[str, ...] = (
    "README.md",
    "docs/*.md",
    "docs/reviews/**/*.md",
    "docs/dod/**/*.md",
)

#: Generated pages a glob on ``ALLOWLIST`` would take in, and why they are not read: a
#: generated page's numbers are re-derived by its generator's own ``--check``, which is a
#: stronger gate than a tag.
UNGATED: dict[str, str] = {
    "docs/CODE-MAP.md": "generated by scripts/code_map.py, whose --check holds it to the source",
    "docs/dod/GAP-ANALYSIS.md": (
        "generated by scripts/dod_check.py, whose --check re-derives every count on it"
    ),
}


def expand(root: Path, allow: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """``(pages, empty)``: every page the entries name — a glob (``docs/*.md``,
    ``docs/reviews/**/*.md``) expanded, in order, without duplicates or ``UNGATED`` pages —
    and the glob entries that match no page at all."""
    pages: list[str] = []
    empty: list[str] = []
    for entry in allow:
        if any(ch in entry for ch in "*?["):
            found = sorted(q.relative_to(root).as_posix() for q in root.glob(entry) if q.is_file())
            found = [rel for rel in found if rel not in UNGATED]
            if not found:
                empty.append(entry)
        else:
            found = [entry]
        pages += [rel for rel in found if rel not in pages]
    return pages, empty


#: The pages the promise rule reads: the allowlist and the claims policy itself (P-235).
PROMISE_PAGES: tuple[str, ...] = (*ALLOWLIST, "docs/EVIDENCE-AND-CLAIMS.md")
#: Where the definition of done's criteria live — a promise's criterion is read from there.
DOD_DIR = "docs/dod"


@dataclass(frozen=True)
class Promise:
    """A capability a page may state in the present tense only once ``criterion`` is met."""

    pattern: re.Pattern[str]
    criterion: str
    says: str


#: Registered promises (P-235). A sentence on a ``PROMISE_PAGES`` page that matches
#: ``pattern`` is refused while ``criterion`` is not ``met`` in docs/dod/. A future tense
#: ("will name") is not the present one, so the page may say what is coming and cite its gap.
_NAMING = r"(?<!will )\b(?:names?|maps?|lists?|shows?)\s+(?:which|each|the)\b"
PROMISES: tuple[Promise, ...] = (
    Promise(
        re.compile(rf"25010.*{_NAMING}|{_NAMING}.*25010", re.I),
        "product.claims.210",
        "that the product names which ISO/IEC 25010 characteristics its checks evidence",
    ),
)

#: Where reviews live, and where a review action's record must be.
REVIEWS_DIR = "docs/reviews"
DECISION_LOG = "docs/DECISION-LOG.md"
#: The states a review action's record may declare.
ACTION_STATES: tuple[str, ...] = ("closed", "open", "declined", "[gap]")

#: The permitted tags — docs/EVIDENCE-AND-CLAIMS.md §1.
TAGS: tuple[str, ...] = ("measured", "hypothesis", "aspiration", "gap")

#: Cardinals written as words. "one" is absent on purpose: "one team learns" is a verb, not a
#: count of a plural noun, and English does not put "one" in front of one.
NUMBER_WORDS: tuple[str, ...] = (
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
)
#: Plural nouns that count parts of a document or a design, not outcomes.
STRUCTURAL: frozenset[str] = frozenset(
    {
        "alternatives",
        "categories",
        "characters",
        "files",
        "halves",
        "kinds",
        "letters",
        "levels",
        "lines",
        "numbers",
        "options",
        "others",
        "parts",
        "places",
        "questions",
        "reasons",
        "sections",
        "sentences",
        "sorts",
        "steps",
        "things",
        "ways",
        "words",
    }
)
#: Function words (including the adverbs and conjunctions that end in "s", which are the
#: heuristic's commonest false plural): a cardinal beside one of these is not counting it.
FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "across",
        "always",
        "an",
        "and",
        "are",
        "as",
        "at",
        "but",
        "by",
        "for",
        "from",
        "his",
        "her",
        "if",
        "in",
        "is",
        "it",
        "its",
        "no",
        "not",
        "of",
        "on",
        "or",
        "otherwise",
        "our",
        "per",
        "perhaps",
        "plus",
        "so",
        "than",
        "that",
        "the",
        "their",
        "these",
        "this",
        "those",
        "thus",
        "to",
        "unless",
        "versus",
        "was",
        "were",
        "when",
        "whereas",
        "which",
        "with",
    }
)

#: A cardinal: grouped ("1,200"), ungrouped ("1200" — a count is a count however it is
#: punctuated), decimal, or written as a word. A leading zero marks an identifier
#: ("ADR-0011"), never a count, and is excluded in ``is_claim``.
_CARDINAL = r"(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d{4,}(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")"
_COUNT_RE = re.compile(rf"\b({_CARDINAL})\s+(?:([a-z][\w'-]*)\s+)?([a-z][\w'-]{{2,}}s)\b", re.I)
_PLURAL_RE = re.compile(r"[a-z][\w'-]{2,}s", re.I)
#: A percentage: "95%", "95 %", and written in words — "95 percent", "95 per cent",
#: "ninety percent", "ninety-five per cent" (P-247).
_NUMBER_WORD = r"(?:" + "|".join(NUMBER_WORDS) + r")(?:-(?:one|" + "|".join(NUMBER_WORDS) + r"))?"
_PERCENT = (
    r"(?:\d[\d,]*(?:\.\d+)?\s?%"
    rf"|(?:\d[\d,]*(?:\.\d+)?|\b{_NUMBER_WORD})\s+per\s?cent\b)"
)
_PERCENT_RE = re.compile(_PERCENT, re.I)
#: A percentage that *is* a confidence level, matched by its construction rather than by a
#: nearby word: "Wilson 95% interval", "95% confidence interval", "95% CI", "at a
#: confidence of 95%". A result standing beside such an interval ("65% passed (Wilson 95%
#: interval)") is not exempted, because the exemption covers only the span it matches.
#:
#: The word ``confidence`` on its own exempts nothing. "There is 65% confidence that the
#: builder can deliver" is an outcome claim, not an interval, and it used to pass the gate
#: untagged because the ``interval|level`` half of the phrase was optional. The exemption now
#: needs the whole noun ("confidence interval", "confidence level") or the construction that
#: makes the percentage the confidence itself ("a confidence of 95%").
_INTERVAL_NOUN = r"(?:confidence\s+(?:interval|level)|interval)"
_CONFIDENCE_PERCENT_RE = re.compile(
    rf"{_PERCENT}\s+(?:{_INTERVAL_NOUN}|ci)\b"
    rf"|\b{_INTERVAL_NOUN}(?:\s+(?:of|at|is|was))?\s+{_PERCENT}"
    rf"|\bconfidence\s+(?:of|at|is|was)\s+{_PERCENT}"
    rf"|\bWilson[\s-]+{_PERCENT}",
    re.I,
)
_TAG_RE = re.compile(r"\[(" + "|".join(TAGS) + r")\b([^\]]*)\]", re.I)
_N_RE = re.compile(r"\bn\s*(?:=|≥|>=|of)\s*\d|\b\d[\d,]*\s*(?:/|of)\s*\d", re.I)
_APPARATUS_RE = re.compile(r"apparatus\s+(?:\d+\.\d+|n/a|none|[a-z0-9.-]+)", re.I)
_CODE_RE = re.compile(r"`[^`]*`")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
#: A section that lists what must never be said (EVIDENCE-AND-CLAIMS §7): its sentences are
#: quoted in order to forbid them, not claimed.
_FORBIDDEN_SECTION_RE = re.compile(
    r"\bmust\s+never\s+be\s+said\b|\bmust\s+not\s+be\s+said\b|\bnever\s+be\s+said\b", re.I
)
#: Nouns that name a member of a numbered series: the cardinal after one says which one
#: ("belt 3", "stage 3", "Wave 2", "rank 23"), not how many — when it reads as a noun
#: (``_names_one``). A word that is mostly a verb or a gerund ("pass 45 tests", "finding 40
#: defects", "round 12 estimates") is not on it, and the list is pinned by a test, because it
#: exempts counts on every gated page (P-240).
NAMING_NOUNS: tuple[str, ...] = (
    "belt",
    "step",
    "stage",
    "wave",
    "item",
    "rank",
    "phase",
    "rung",
    "tier",
    "level",
    "section",
    "table",
    "figure",
    "chapter",
    "appendix",
    "arm",
    "column",
    "page",
    "version",
    "mutation",
    "migration",
    "revision",
    "criterion",
    "slice",
    "batch",
)
_NAMING_NOUN_RE = re.compile(rf"\b(?:{'|'.join(NAMING_NOUNS)})\s+$", re.I)
#: Words after which a naming noun reads as a noun ("at stage 3", "the belt 3 check"), not
#: as a verb ("can batch 40 jobs", "will stage 12 releases"). "to" is absent on purpose:
#: "to batch 40 jobs" is a verb.
_NOUN_CONTEXT: frozenset[str] = frozenset(
    {
        "a",
        "after",
        "and",
        "at",
        "before",
        "by",
        "each",
        "every",
        "for",
        "from",
        "in",
        "into",
        "its",
        "of",
        "on",
        "or",
        "per",
        "the",
        "their",
        "this",
        "through",
        "under",
        "until",
        "with",
    }
)


def _names_one(before: str) -> bool:
    """True when the text before a cardinal ends in a naming noun that reads as a noun:
    capitalised ("Belt 3", "Wave 2"), at the start of the sentence or after a bracket or
    a comma, after a determiner or a preposition ("at stage 3"), or after an identifier
    ("ADR-0026 item 11"). After anything else — a subject or a modal — it is a verb, and
    the count after it is a count ("the worker can batch 40 jobs", P-240)."""
    m = _NAMING_NOUN_RE.search(before)
    if not m:
        return False
    if m.group(0)[0].isupper():
        return True
    preceding = before[: m.start()].rstrip()
    if not preceding or preceding[-1] in "([,;:\u2014\u2013":
        return True
    word = preceding.split()[-1]
    return word.lower() in _NOUN_CONTEXT or any(ch.isdigit() for ch in word)


_ANCHOR_LINK_RE = re.compile(r"\[[^\]]*\]\(#[^)]*\)")
#: What may sit between the links of a contents line: separators and a short label.
_CONTENTS_REST_RE = re.compile(r"^[\s·|•,;:>*+-]*(?:[A-Za-z ]{1,20}:)?[\s·|•,;:>*+-]*$")
#: A definition-of-done gap register line, in ``dod_check``'s own grammar:
#: ``- **G-nnn** — what is missing · what closes it · owner``. Its form is a [gap] tag — it
#: names what is absent and what would close it, which is what the tag must cite
#: (EVIDENCE-AND-CLAIMS §1) — but only where ``dod_check`` reads it as a gap: under a
#: ``## Gaps`` heading on a definition-of-done page or in the prevention register (P-240).
_GAP_LINE_RE = re.compile(r"^\*\*G-\d{3}\*\*\s*—\s*\S.*·.*·")
_GAP_PAGES_RE = re.compile(r"^(?:docs/dod/.+\.md|docs/PREVENTION\.md)$")
_GAPS_HEADING_RE = re.compile(r"^#{2}\s+Gaps\b", re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
#: The CommonMark parser that decides where a fenced code block starts and ends. Tables are
#: on because GitHub renders a review's Actions table as one.
_MARKDOWN = MarkdownIt("commonmark").enable("table")
_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_CHECKLIST_RE = re.compile(r"^\s*[-*+]\s+\[[ xX]\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
#: A ``[measured]`` tag that says its own rows are not here contradicts itself (DL-088): a
#: reading nobody can re-derive from the repository is a ``[hypothesis]`` with that reason.
_NOT_HERE_RE = re.compile(
    r"\bnot\s+in\s+this\s+repository\b|\bnot\s+vendored\b|\boperator's\s+(?:stack|export)\b",
    re.I,
)
#: A method is checked for presence only: words inside the tag beyond its n and its apparatus.
METHOD_MIN_WORDS = 5


@dataclass(frozen=True)
class Finding:
    """One sentence that does not carry what the policy asks of it."""

    path: str
    line: int
    sentence: str
    reason: str


@dataclass
class Block:
    """A paragraph or list item, with the text a tag may cover it from."""

    line: int
    text: str
    cover: str
    heading: str = ""


def _strip_markup(text: str) -> str:
    """Inline code, link targets and HTML comments carry no claims of their own."""
    text = _COMMENT_RE.sub(" ", text)
    text = _CODE_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    return text.replace("**", "").replace("*", "").replace("> ", " ")


def _lines_with_fences(text: str) -> Iterator[tuple[int, str, bool]]:
    """``(line number, line, fenced)`` for every line; ``fenced`` is true for a fenced code
    block's own delimiters and everything between them, exactly as a CommonMark parser with
    GitHub's tables on reads the page. Every reader of a page's structure goes through here,
    so a fenced example is never read as prose or as a review's action.

    The spans come from ``markdown-it-py``, not from a line-by-line reading of §4.5. PR #54's
    review found five places where a hand-rolled reader disagreed with CommonMark — the
    closer's character, its info string, its indent, a marker inside an HTML comment, and a
    fence inside a list item — and each one let a fence swallow real Actions rows so that
    ``--check`` passed without their records. A fence's extent depends on the containers
    around it (lists, blockquotes, HTML blocks), so the only reader that cannot drift from
    CommonMark is a CommonMark parser."""
    lines = re.sub(r"\r\n?", "\n", text).split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # a final newline ends the last line; it does not start another
    fenced = [False] * len(lines)
    for token in _MARKDOWN.parse(text):
        if token.type == "fence" and token.map:
            for i in range(token.map[0], min(token.map[1], len(lines))):
                fenced[i] = True
    for number, raw in enumerate(lines, start=1):
        yield number, raw.rstrip(), fenced[number - 1]


def _unrendered(text: str) -> tuple[set[int], dict[int, str]]:
    """``(hidden, tails)``: the line numbers (1-based) a reader never sees as prose — an HTML
    comment block (a file's Navigation header, even across blank lines) and a leading
    front-matter block — and, for a comment block whose closing line carries text after
    ``-->``, that text, which GitHub renders and the gate therefore reads (P-240)."""
    hidden: set[int] = set()
    tails: dict[int, str] = {}
    lines = re.sub(r"\r\n?", "\n", text).split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                hidden.update(range(1, i + 2))
                break
    for token in _MARKDOWN.parse(text):
        if token.type == "html_block" and token.map and token.content.lstrip().startswith("<!--"):
            first, last = token.map[0] + 1, token.map[1]
            hidden.update(range(first, last + 1))
            closing = lines[last - 1] if last - 1 < len(lines) else ""
            tail = closing.rsplit("-->", 1)[1].strip() if "-->" in closing else ""
            if tail:
                tails[last] = tail
    return hidden, tails


def _contents_prose(text: str) -> str:
    """A block as the gate reads it. On a contents line — nothing but links, at least one to
    a heading on the same page, joined by separators and at most a short label
    ("Contents:") — a same-page link's text is dropped: a heading is not a claim, so its
    link is not one either. Anywhere else, and for a contents line's links to other pages, a
    link reads as the words it shows (P-240)."""
    if _ANCHOR_LINK_RE.search(text) and _CONTENTS_REST_RE.match(_LINK_RE.sub(" ", text)):
        return _ANCHOR_LINK_RE.sub(" ", text)
    return text


_TABLE_RULE_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _cells(row: str) -> list[str]:
    """The non-empty cells of a table row (a ``\\|`` inside a cell is not a divider)."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|")) if c.strip()]


def blocks_of(text: str, *, rendered: bool = False) -> list[Block]:
    """The page's prose blocks, each with the text that may tag it.

    Headings, table rows, fenced code and checklist items are not prose and are skipped. A
    list item's cover is its own text plus the paragraph that introduced the list.

    With ``rendered``, every shape a reader reads is a block too: a heading (its own text),
    each cell of a table row, and a checklist item (read as a list item, so the paragraph
    that introduces it covers it). The claim-tag heuristic counts only prose; a rule about
    what a page *says* — the conformity rule, a README ``[measured]`` tag's rows and their
    re-derivation, a registered promise — reads everything that renders (P-246).
    """
    out: list[Block] = []
    paragraph: list[str] = []
    start = 0
    intro = ""
    item: list[str] = []
    item_start = 0
    heading = ""

    def close_paragraph() -> None:
        nonlocal paragraph, intro
        if paragraph:
            intro = _contents_prose(" ".join(paragraph))
            if intro.strip():
                out.append(Block(start, intro, intro, heading))
            paragraph = []

    def close_item() -> None:
        nonlocal item
        if item:
            body = _contents_prose(" ".join(item))
            if body.strip():
                out.append(Block(item_start, body, f"{intro} {body}", heading))
            item = []

    hidden, tails = _unrendered(text)
    for number, raw, fenced in _lines_with_fences(text):
        line = raw
        if number in tails and not fenced:
            close_paragraph()
            close_item()
            line = tails[number]
        elif fenced or number in hidden:
            close_paragraph()
            close_item()
            continue
        stripped = line.strip()
        quoted = stripped[2:].strip() if stripped.startswith("> ") else stripped
        if not quoted or _HEADING_RE.match(quoted) or quoted.startswith("|"):
            close_paragraph()
            close_item()
            if _HEADING_RE.match(quoted):
                intro = ""
                heading = quoted
                if rendered:
                    words = re.sub(r"^#{1,6}\s+|\s+#+\s*$", "", quoted)
                    out.append(Block(number, words, words, heading))
            elif rendered and quoted.startswith("|") and not _TABLE_RULE_RE.match(quoted):
                out += [Block(number, cell, cell, heading) for cell in _cells(quoted)]
            continue
        if _CHECKLIST_RE.match(quoted):
            close_paragraph()
            close_item()
            if rendered:
                item = [re.sub(r"^\s*[-*+]\s+\[[ xX]\]\s*", "", quoted)]
                item_start = number
            continue
        if _ITEM_RE.match(quoted):
            close_paragraph()
            close_item()
            item = [_ITEM_RE.sub("", quoted)]
            item_start = number
            continue
        if item:
            item.append(quoted)
            continue
        if not paragraph:
            start = number
        paragraph.append(quoted)
    close_paragraph()
    close_item()
    return out


def claim_numbers(sentence: str) -> list[str]:
    """The figures that make the sentence a claim — each percentage that is not a confidence
    level and each cardinal qualifying a plural noun (see the module docstring); empty when
    the sentence quantifies nothing. tests/test_measured_claims.py re-derives these."""
    text = _strip_markup(sentence).strip()
    if not text or text.endswith(":"):
        return []
    out: list[str] = []
    confidence = [m.span() for m in _CONFIDENCE_PERCENT_RE.finditer(text)]
    for match in _PERCENT_RE.finditer(text):
        if not any(start <= match.start() < end for start, end in confidence):
            out.append(match.group(0))
    for match in _COUNT_RE.finditer(text):
        cardinal, between, noun = match.group(1), match.group(2), match.group(3)
        if between and noun.lower() in FUNCTION_WORDS and _PLURAL_RE.fullmatch(between):
            # "12 releases this year": the optional middle word took the plural noun and left
            # a function word that merely ends in "s" in its place (P-240)
            between, noun = None, between
        if between and between.lower() in FUNCTION_WORDS:
            continue
        if noun.lower() in STRUCTURAL or noun.lower() in FUNCTION_WORDS:
            continue
        before = text[: match.start(1)]
        if before.endswith(("§", "#")) or re.search(r"[A-Za-z]-$", before):
            continue  # "§9", "PR #48", "G-674" — a section, a pull request, an id: not a count
        if _names_one(before):
            continue  # "belt 3", "stage 3", "item 11" — which one, not how many
        digits = cardinal.replace(",", "")
        if digits.replace(".", "").isdigit():
            if digits.startswith("0") and not digits.startswith("0."):
                continue  # "ADR-0011", "DL-0052" — an identifier, not a count
            value = float(digits)
            if value <= 1 or (value.is_integer() and 1900 <= value <= 2099):
                continue
        out.append(cardinal)
    return out


def is_claim(sentence: str) -> bool:
    """True when the sentence quantifies something (see the module docstring)."""
    return bool(claim_numbers(sentence))


def tag_defects(cover: str) -> list[str] | None:
    """``None`` when no permitted tag covers the claim; else what the tag still owes.

    ``n`` and the apparatus version may sit anywhere the tag covers — a README section tags
    its apparatus once at the head and each bullet carries its own ``n``. The *method* is
    read inside the tag itself, because that is where "how this was produced" belongs.
    """
    prose = _CODE_RE.sub(" ", _COMMENT_RE.sub(" ", cover))
    tags = _TAG_RE.findall(prose)
    if not tags:
        return None
    details = [detail for name, detail in tags if name.lower() == "measured"]
    if not details:
        return []
    defects: list[str] = []
    if not _N_RE.search(cover):
        defects.append("[measured] without n")
    if not any(_method_words(detail) >= METHOD_MIN_WORDS for detail in details):
        defects.append("[measured] without a method")
    if not _APPARATUS_RE.search(cover):
        defects.append("[measured] without an apparatus version")
    if any(_NOT_HERE_RE.search(detail) for detail in details):
        defects.append(
            "[measured] whose rows are not in this repository — nobody can re-derive it here, "
            "so tag it [hypothesis] with that reason (DL-088)"
        )
    return defects


def _method_words(detail: str) -> int:
    """Words inside a ``[measured …]`` tag once its n and its apparatus are taken out."""
    rest = _APPARATUS_RE.sub(" ", _N_RE.sub(" ", detail))
    return len([w for w in re.split(r"[^A-Za-z]+", rest) if len(w) > 1])


def check_text(rel: str, text: str) -> list[Finding]:
    """Every finding on one page, in the order a reader meets them.

    One finding per defect per block, naming the block's first claim sentence: the fix is to
    the block's tag, so a block with three untagged claims is one piece of work, not three.
    """
    findings: list[Finding] = []
    for block in blocks_of(text):
        claims = [s for s in _SENTENCE_SPLIT.split(block.text) if is_claim(s)]
        if not claims:
            continue
        if _FORBIDDEN_SECTION_RE.search(block.heading):
            continue  # a sentence quoted in order to forbid it is not a claim
        defects = tag_defects(block.cover)
        if (
            defects is None
            and _GAP_PAGES_RE.match(rel)
            and _GAPS_HEADING_RE.match(block.heading)
            and _GAP_LINE_RE.match(block.text)
        ):
            continue  # a gap register line is its own [gap] tag; a [measured] in it still owes
        reasons = ["no claim tag"] if defects is None else defects
        for reason in reasons:
            findings.append(Finding(rel, block.line, claims[0].strip(), reason))
    return findings


def check_tree(root: Path, allow: tuple[str, ...]) -> list[Finding]:
    """Every finding across the allowlisted pages of ``root`` (globs expanded)."""
    pages, empty = expand(root, allow)
    findings = [Finding(entry, 0, "", "on the allowlist but matches nothing") for entry in empty]
    for rel in pages:
        path = root / rel
        if not path.is_file():
            findings.append(Finding(rel, 0, "", "on the allowlist but absent"))
            continue
        findings.extend(check_text(rel, path.read_text(encoding="utf-8")))
    return findings


_CRITERION_ROW_RE = re.compile(r"^\|\s*([a-z0-9-]+(?:\.[a-z0-9-]+)+\.\d+)\s*\|")


def criterion_states(root: Path) -> dict[str, str]:
    """Each criterion id under docs/dod/ with its state (the row's second-last cell)."""
    out: dict[str, str] = {}
    base = root / DOD_DIR
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.md")):
        if path.name == "GAP-ANALYSIS.md":
            continue
        for line in path.read_text(encoding="utf-8").split("\n"):
            m = _CRITERION_ROW_RE.match(line)
            if m:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 6:
                    out.setdefault(m.group(1), cells[-2])
    return out


def check_promises(root: Path, pages: tuple[str, ...]) -> list[Finding]:
    """A registered capability stated in the present tense before its criterion is met
    (P-235): the README said the product names which ISO/IEC 25010 characteristics its checks
    evidence while the criterion that builds that table was unmet."""
    findings: list[Finding] = []
    if not (root / DOD_DIR).is_dir():
        return findings  # a tree with no definition of done has no promise to hold
    states = criterion_states(root)
    for promise in PROMISES:
        if promise.criterion not in states:
            findings.append(
                Finding(
                    DOD_DIR,
                    0,
                    "",
                    f"the promise {promise.says!r} names {promise.criterion}, but no criterion "
                    "has that id — update PROMISES in scripts/claims_check.py",
                )
            )
    for rel in expand(root, pages)[0]:
        path = root / rel
        if not path.is_file():
            continue
        for block in blocks_of(path.read_text(encoding="utf-8"), rendered=True):
            for sentence in _SENTENCE_SPLIT.split(_strip_markup(block.text)):
                for promise in PROMISES:
                    state = states.get(promise.criterion)
                    if state is None or state == "met":
                        continue
                    if promise.pattern.search(sentence):
                        findings.append(
                            Finding(
                                rel,
                                block.line,
                                sentence.strip(),
                                f"states {promise.says} while {promise.criterion} is {state} — "
                                "say what exists now, and what is coming in the future tense "
                                "with its gap",
                            )
                        )
    return findings


# ─── a README [measured] tag names the rows it rests on (G-660) ──────────────────────────

#: The pages whose ``[measured]`` tags must name vendored rows: the most public page.
ROWS_PAGES: tuple[str, ...] = ("README.md",)
#: The checksum manifest every vendored campaign carries (``shasum -a 256`` format).
MANIFEST = "MANIFEST.sha256"
#: Files a campaign directory may hold outside its manifest: the manifest and its README.
UNMANIFESTED: frozenset[str] = frozenset({MANIFEST, "README.md"})
#: ``rows: data/<campaign>/`` inside the tag, written plain (not in backticks).
_ROWS_RE = re.compile(r"\brows:\s*(data/[A-Za-z0-9._-]+)/?")


def rows_locators(detail: str) -> list[str]:
    """The ``data/<campaign>`` directories a ``[measured …]`` tag's text names."""
    return _ROWS_RE.findall(detail)


def verify_manifest(root: Path, campaign: str) -> list[str]:
    """What is wrong with a vendored campaign's rows: a listed file absent or changed, a
    file present but not listed. Empty when the manifest verifies."""
    base = root / campaign
    manifest = base / MANIFEST
    if not manifest.is_file():
        return [f"no checksum manifest ({MANIFEST})"]
    problems: list[str] = []
    listed: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        rel = rel.strip().removeprefix("./")
        listed.add(rel)
        path = base / rel
        if not path.is_file():
            problems.append(f"{rel} is listed but absent")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest.strip():
            problems.append(f"{rel} does not match its checksum")
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base).as_posix()
        if path.is_file() and rel not in listed and rel not in UNMANIFESTED:
            problems.append(f"{rel} is not in the manifest")
    return problems


def check_rows(root: Path, pages: tuple[str, ...] = ROWS_PAGES) -> list[Finding]:
    """Every ``[measured]`` tag on ``pages`` names rows the repository carries, under a
    checksum manifest that verifies (G-660). The numbers themselves are re-derived from
    those rows by tests/test_measured_claims.py; this gate holds the shape."""
    findings: list[Finding] = []
    for rel in pages:
        path = root / rel
        if not path.is_file():
            continue
        for block in blocks_of(path.read_text(encoding="utf-8"), rendered=True):
            prose = _CODE_RE.sub(" ", _COMMENT_RE.sub(" ", block.text))
            for name, detail in _TAG_RE.findall(prose):
                if name.lower() != "measured":
                    continue
                sentence = _SENTENCE_SPLIT.split(block.text)[0].strip()
                locators = rows_locators(detail)
                if not locators:
                    findings.append(
                        Finding(
                            rel,
                            block.line,
                            sentence,
                            "[measured] on this page names no rows — add rows: "
                            "data/<campaign>/ for rows the repository carries, or retag the "
                            "claim (G-660)",
                        )
                    )
                for loc in locators:
                    if not (root / loc).is_dir():
                        reason = (
                            f"[measured] names rows at {loc}/, which the repository does not carry"
                        )
                    else:
                        problems = verify_manifest(root, loc)
                        if not problems:
                            continue
                        if problems[0].startswith("no checksum manifest"):
                            reason = f"[measured] names rows at {loc}/, which have {problems[0]}"
                        else:
                            reason = (
                                f"[measured] names rows at {loc}/, which do not verify against "
                                f"their manifest: {'; '.join(problems)}"
                            )
                    findings.append(Finding(rel, block.line, sentence, reason))
    return findings


# ─── the quality baseline is named, never claimed (ADR-0026 item 11) ─────────────────────

#: Where the UI declares the guides it bundles; the conformity rule reads those guides.
BUNDLED_GUIDES_TS = "ui/src/help/docs.ts"
#: The factory's pull-request body template: the string literals of these functions.
PR_BODY_SOURCE = "src/crb/factory/delivery.py"
PR_BODY_FUNCTIONS: tuple[str, ...] = ("pr_body", "rework_comment")

_DOC_NAMES_RE = re.compile(r"export const DOC_NAMES\s*=\s*\[([^\]]*)\]")
#: A verb or adjective of conformity: conforms, complies, compliant, certified …
#: ("certificate" is not one — the TLS guides name certificates).
_CONFORM_RE = re.compile(
    r"\b(?:conform(?:s|ed|ing|ant|ance|ity)?|compl(?:y|ies|ied|iant|iance)"
    r"|certif(?:y|ies|ied|ication))\b",
    re.I,
)
#: An ISO standard, named: "ISO/IEC 25010", "ISO 9001", "an ISO standard", "iso/iec 25010",
#: "ISO25010" — in any case, and with or without a space before its number (P-245).
_ISO_RE = re.compile(r"\bISO(?:\b|(?=\d))", re.I)
#: Words that negate the verb they stand in front of. "no" and "without" are absent on
#: purpose: they govern a noun ("no doubt", "without exception"), never the conformity verb.
_NEGATIONS: frozenset[str] = frozenset({"never", "not", "nor", "cannot"})
#: What may stand between a negation and the verb it negates: an auxiliary, an adverb that
#: does not turn the negation ("does not formally conform"), an article, and the standard's
#: own name ("is not ISO/IEC 25010 compliant"). "only", "just", "merely" and "simply" are
#: absent on purpose: "not only conforms" asserts it (P-245).
_VERB_GROUP: frozenset[str] = frozenset(
    {
        "a",
        "am",
        "an",
        "are",
        "automatically",
        "be",
        "been",
        "being",
        "can",
        "could",
        "did",
        "do",
        "does",
        "ever",
        "formally",
        "fully",
        "had",
        "has",
        "have",
        "iec",
        "is",
        "iso",
        "itself",
        "may",
        "might",
        "must",
        "necessarily",
        "officially",
        "shall",
        "should",
        "thereby",
        "therefore",
        "thus",
        "was",
        "were",
        "will",
        "would",
        "yet",
    }
)
#: A verb whose complement may carry the conformity claim: when it is itself negated, the
#: claim in its complement is denied ("does not mean the code complies", "never certifies
#: that code conforms", "does not make the code compliant").
_REPORTING = re.compile(
    r"^(?:mean|imply|impli|say|said|show|prove|make|guarantee|establish|certif|claim|assert"
    r"|state|entail|warrant|demonstrat|tell|told)",
    re.I,
)
#: A verb that refuses or forbids a saying ("the gate refuses a sentence that says code
#: conforms …"), and the saying it must govern, in the same clause, before the claim.
_REFUSAL_RE = re.compile(r"^(?:refus|forbid|reject|prohibit)", re.I)
_SAYING_RE = re.compile(
    r"^(?:sentences?|claims?|claiming|statements?|stating|says?|saying|wording|words?)$", re.I
)
#: What ends a clause when looking back from a conformity word for a verb that denies it.
_CLAUSE_BREAKS: frozenset[str] = frozenset(
    {
        ",",
        ";",
        ":",
        "\u2014",
        "\u2013",
        "(",
        ")",
        "but",
        "and",
        "or",
        "so",
        "while",
        "although",
        "though",
        "because",
    }
)
#: What may join two conformity words in one coordinated list ("conforms to, complies with
#: or is certified against"): the second shares the first's denial.
_COORDINATION: frozenset[str] = frozenset(
    {",", "to", "with", "against", "by", "or", "and", "nor", "is", "are", "be", "been"}
)
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[,;:\u2014\u2013()]")


def _negated(words: list[str], at: int) -> bool:
    """True when a negation stands directly in front of ``words[at]``'s verb group: only
    auxiliaries, adverbs that do not turn it, articles and the standard's name between."""
    for w in reversed(words[:at]):
        lower = w.lower()
        if lower in _NEGATIONS or lower.endswith("n't"):
            return True
        if lower not in _VERB_GROUP:
            return False
    return False


def _clause_before(words: list[str], at: int) -> list[int]:
    """The indices of the words before ``words[at]`` in its own clause, nearest first."""
    out: list[int] = []
    for i in range(at - 1, -1, -1):
        if words[i].lower() in _CLAUSE_BREAKS:
            break
        out.append(i)
    return out


def _denied(words: list[str], at: int, denied: set[int]) -> bool:
    """True when the conformity word at ``words[at]`` is denied: negated in its own verb
    group ("does not conform"); in the complement of a negated reporting verb in its own
    clause ("does not mean the code complies"); in the complement of a refused saying in its
    own clause ("refuses a sentence that says code conforms"); or coordinated with a denied
    conformity word ("conforms to, complies with or is certified against"). A negation or a
    refusal anywhere else in the sentence denies nothing (P-240, P-245)."""
    if _negated(words, at):
        return True
    clause = _clause_before(words, at)
    for i in clause:
        if _REPORTING.match(words[i]) and _negated(words, i):
            return True
        if _SAYING_RE.match(words[i]) and any(_REFUSAL_RE.match(words[j]) for j in clause if j < i):
            return True
    for prev in sorted(denied, reverse=True):
        if prev < at and all(w.lower() in _COORDINATION for w in words[prev + 1 : at]):
            return True
    return False


def conformity_claim(sentence: str) -> bool:
    """True when the sentence says code conforms to, complies with or is certified against
    an ISO standard: it names one, and some conformity word in it is not denied (``_denied``).
    A sentence that only names a standard, or denies the claim, is not one."""
    text = _strip_markup(sentence)
    if not _ISO_RE.search(text):
        return False
    words = _WORD_RE.findall(text)
    denied: set[int] = set()
    for i, w in enumerate(words):
        if not _CONFORM_RE.fullmatch(w):
            continue
        if not _denied(words, i, denied):
            return True
        denied.add(i)
    return False


def bundled_guides(root: Path) -> tuple[str, ...] | None:
    """The guides the UI bundles (``DOC_NAMES``), as repository paths; ``None`` when the
    list cannot be read."""
    path = root / BUNDLED_GUIDES_TS
    if not path.is_file():
        return None
    m = _DOC_NAMES_RE.search(path.read_text(encoding="utf-8"))
    if not m:
        return None
    names = re.findall(r"['\"]([A-Za-z0-9_-]+)['\"]", m.group(1))
    return tuple(f"docs/{n}.md" for n in names) or None


#: What an interpolated value the rule cannot resolve reads as: a standard. Beside a
#: conformity word it is refused, because the rule cannot show it is not one (P-246).
HOLE = "ISO(an interpolated value)"
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}|%[sdr]")


def _module_constants(tree: ast.Module) -> dict[str, ast.AST]:
    """Each module-level ``NAME = <value>`` (annotated or not) of a parsed module."""
    constants: dict[str, ast.AST] = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and n.value is not None:
            for target in n.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = n.value
        elif (
            isinstance(n, ast.AnnAssign) and n.value is not None and isinstance(n.target, ast.Name)
        ):
            constants[n.target.id] = n.value
    return constants


class _Resolver:
    """Resolves a value a string interpolates to the text it holds: a string literal, a
    module constant, or a constant imported from another ``crb`` module (``from crb.x import
    NAME``, ``import crb.x as m`` then ``m.NAME``). ``None`` when it cannot."""

    def __init__(self, root: Path, tree: ast.Module) -> None:
        self.root = root
        self.constants = _module_constants(tree)
        self.names: dict[str, tuple[str, str]] = {}  # local name -> (module, attribute)
        self.modules: dict[str, str] = {}  # local alias -> module
        for n in tree.body:
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                for alias in n.names:
                    self.names[alias.asname or alias.name] = (n.module, alias.name)
            elif isinstance(n, ast.Import):
                for alias in n.names:
                    if alias.asname:
                        self.modules[alias.asname] = alias.name
        self._foreign: dict[str, dict[str, ast.AST]] = {}

    def _foreign_constant(self, module: str, name: str) -> str | None:
        if module not in self._foreign:
            path = self.root / "src" / Path(*module.split(".")).with_suffix(".py")
            self._foreign[module] = (
                _module_constants(ast.parse(path.read_text(encoding="utf-8")))
                if path.is_file()
                else {}
            )
        value = self._foreign[module].get(name)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        return None

    def text(self, node: ast.AST, depth: int = 0) -> str | None:
        if depth > 8:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.constants:
                return self.text(self.constants[node.id], depth + 1)
            if node.id in self.names:
                return self._foreign_constant(*self.names[node.id])
            return None
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.modules
        ):
            return self._foreign_constant(self.modules[node.value.id], node.attr)
        if isinstance(node, (ast.JoinedStr, ast.BinOp)):
            return _render(node, self, depth + 1)
        return None


def _add_chain(node: ast.AST) -> list[ast.AST]:
    """The operands of an ``a + b + c`` chain, left to right."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [*_add_chain(node.left), *_add_chain(node.right)]
    return [node]


def _render(node: ast.AST, resolver: _Resolver, depth: int = 0) -> str | None:
    """The text an f-string or a ``+`` join of strings emits, each value it interpolates
    resolved (``_Resolver``) or read as ``HOLE``; ``None`` for anything else."""
    parts: list[ast.AST]
    if isinstance(node, ast.JoinedStr):
        parts = list(node.values)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        parts = _add_chain(node)
        if not any(isinstance(p, (ast.Constant, ast.JoinedStr)) for p in parts):
            return None
    else:
        return None
    out: list[str] = []
    for part in parts:
        value = part.value if isinstance(part, ast.FormattedValue) else part
        text = resolver.text(value, depth)
        out.append(HOLE if text is None else text)
    return "".join(out)


def _literals(node: ast.AST, resolver: _Resolver) -> list[tuple[int, str]]:
    """``(line, text)`` for every string under ``node`` as it is emitted: an f-string or a
    ``+`` join is rendered whole, with each value it interpolates resolved or read as
    ``HOLE``, and a literal's own ``{}``/``%s`` placeholders (``.format``, ``%``) read as
    ``HOLE`` — so a sentence split by a value still reads, and a value that may name a
    standard is not dropped (P-246)."""
    out: list[tuple[int, str]] = []
    consumed: set[int] = set()
    for sub in ast.walk(node):
        if id(sub) in consumed:
            continue
        if isinstance(sub, (ast.JoinedStr, ast.BinOp)):
            text = _render(sub, resolver)
            if text is not None:
                out.append((sub.lineno, text))
                for inner in ast.walk(sub):
                    if inner is not sub:
                        consumed.add(id(inner))
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append((sub.lineno, _PLACEHOLDER_RE.sub(HOLE, sub.value)))
    return out


def _pr_body_literals(root: Path) -> list[tuple[int, str]] | None:
    """``(line, text)`` for every string the pull-request body can emit: the literals of the
    body functions, of every module-level function they call (and those call), and of every
    module-level constant any of them reads — the body is what ``pr_body`` returns, not
    only what is written inside it (P-240) — each rendered with what it interpolates (P-246)."""
    path = root / PR_BODY_SOURCE
    if not path.is_file():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"))
    resolver = _Resolver(root, tree)
    functions = {
        n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    constants = resolver.constants
    if not any(name in functions for name in PR_BODY_FUNCTIONS):
        return None
    queue = [name for name in PR_BODY_FUNCTIONS if name in functions]
    seen_fn: set[str] = set()
    seen_const: set[str] = set()
    found: set[tuple[int, str]] = set()
    while queue:
        name = queue.pop()
        if name in seen_fn:
            continue
        seen_fn.add(name)
        fn = functions[name]
        found.update(_literals(fn, resolver))
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id in functions and sub.id not in seen_fn:
                    queue.append(sub.id)
                elif sub.id in constants and sub.id not in seen_const:
                    seen_const.add(sub.id)
                    found.update(_literals(constants[sub.id], resolver))
    return sorted(found)


def check_conformity(root: Path, pages: tuple[str, ...] | None = None) -> list[Finding]:
    """A sentence that claims ISO conformity (ADR-0026 item 11), on README, the guides (the
    ones the UI bundles, read from ``DOC_NAMES`` so a newly bundled guide is read the day it
    ships, and every other page directly under docs/) and the factory's pull-request body
    template — or on ``pages`` when given."""
    reason = (
        "a conformity claim — the product names ISO/IEC 25010 and never claims it: say which "
        "characteristics the checks evidence part of (EVIDENCE-AND-CLAIMS §9), not that code "
        "conforms"
    )
    findings: list[Finding] = []
    literals: list[tuple[int, str]] | None = []
    if pages is None:
        guides = bundled_guides(root)
        if guides is None:
            findings.append(
                Finding(
                    BUNDLED_GUIDES_TS,
                    0,
                    "",
                    "cannot read the bundled guides' names (DOC_NAMES); the conformity rule "
                    "would read no guide",
                )
            )
            guides = ()
        others = sorted(
            q.relative_to(root).as_posix()
            for q in (root / "docs").glob("*.md")
            if q.relative_to(root).as_posix() not in guides
        )
        pages = ("README.md", *guides, *others)
        literals = _pr_body_literals(root)
        if literals is None:
            findings.append(
                Finding(
                    PR_BODY_SOURCE,
                    0,
                    "",
                    "cannot find the pull-request body template "
                    f"({', '.join(PR_BODY_FUNCTIONS)}); the conformity rule would read none",
                )
            )
            literals = []
    for rel in pages:
        path = root / rel
        if not path.is_file():
            continue
        for block in blocks_of(path.read_text(encoding="utf-8"), rendered=True):
            if _FORBIDDEN_SECTION_RE.search(block.heading):
                continue  # a section that lists what must never be said quotes it to forbid it
            for sentence in _SENTENCE_SPLIT.split(block.text):
                if conformity_claim(sentence):
                    findings.append(Finding(rel, block.line, sentence.strip(), reason))
    for line, text in literals or []:
        for sentence in _SENTENCE_SPLIT.split(text):
            if conformity_claim(sentence):
                findings.append(Finding(PR_BODY_SOURCE, line, sentence.strip(), reason))
    return findings


_ACTIONS_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s.*\bActions\b")
_ACTION_ROW_RE = re.compile(r"^\s*\|\s*(\d+)\s*\|")
_ACTION_STATE_RE = re.compile(
    r"\baction\s+#(\d+)\s*[:\u2014\u2013-]\s*("
    + "|".join(re.escape(s) for s in ACTION_STATES)
    # a state is a whole word: "opening" is not "open"; "[gap]" ends in "]", so the
    # boundary is a lookahead for a non-word character rather than ``\b``
    + r")(?!\w)",
    re.I,
)


def review_actions(text: str) -> list[tuple[int, int]]:
    """``(action number, line)`` for every row of the review's Actions table(s). A fenced
    example is skipped: its rows are not actions and its headings open no section."""
    out: list[tuple[int, int]] = []
    inside = False
    for number, line, fenced in _lines_with_fences(text):
        if fenced:
            continue
        if _HEADING_RE.match(line):
            inside = bool(_ACTIONS_HEADING_RE.match(line))
            continue
        if inside:
            m = _ACTION_ROW_RE.match(line)
            if m:
                out.append((int(m.group(1)), number))
    return out


#: A record's head: the review's file stem in backticks, directly before ``action #``.
#: Every record after it on the line belongs to that review until the next head — so a
#: stem that a record merely mentions (a path in its evidence) never claims the record.
_RECORD_HEAD_RE = re.compile(r"`([^`\s]+)`\s+(?=action\s+#)", re.I)


def _records(line: str) -> Iterator[tuple[str, int]]:
    """``(review stem, action number)`` for every stated record on one decision-log line."""
    heads = [(m.start(), m.group(1)) for m in _RECORD_HEAD_RE.finditer(line)]
    for m in _ACTION_STATE_RE.finditer(line):
        owner = [stem for start, stem in heads if start < m.start()]
        if owner:
            yield owner[-1], int(m.group(1))


def recorded_actions(log_text: str, stem: str) -> set[int]:
    """The action numbers of review ``stem`` that a decision-log line states a state for,
    under a head that names it (`` `<stem>` action #N: <state>``)."""
    return {n for line in log_text.splitlines() for owner, n in _records(line) if owner == stem}


def _record_line(log_text: str, stem: str, action: int) -> int:
    """The first decision-log line that records ``stem``'s action ``action`` (1-based)."""
    for number, line in enumerate(log_text.splitlines(), start=1):
        if (stem, action) in set(_records(line)):
            return number
    return 0


def check_review_actions(root: Path) -> list[Finding]:
    """A finding for every numbered review action with no stated record in the decision log,
    and for every recorded action its review no longer lists. Checking both ways means
    neither side can vanish alone: a deleted row or a renamed Actions heading leaves records
    pointing at nothing, which is a finding against the decision log. The reviews read are
    the ones on disk AND the ones the log names, so deleting a review file leaves its records
    as findings rather than taking them out of the check."""
    reviews = root / REVIEWS_DIR
    log_path = root / DECISION_LOG
    log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    log_rel = log_path.relative_to(root).as_posix()
    on_disk: dict[str, Path] = {}
    findings: list[Finding] = []
    # every review under the folder, nested ones too; a record names its review by stem, so
    # two reviews that share one are refused rather than one silently taking the other's place
    for p in sorted(reviews.rglob("*.md")) if reviews.is_dir() else []:
        first = on_disk.setdefault(p.stem, p)
        if first != p:
            findings.append(
                Finding(
                    p.relative_to(root).as_posix(),
                    1,
                    "",
                    f"another review has the stem {p.stem} "
                    f"({first.relative_to(root).as_posix()}); a record could not say which it "
                    "closes",
                )
            )
    named = {stem for line in log_text.splitlines() for stem, _ in _records(line)}
    for stem in sorted(set(on_disk) | named):
        path = on_disk.get(stem)
        actions = review_actions(path.read_text(encoding="utf-8")) if path else []
        recorded = recorded_actions(log_text, stem)
        if path is not None:
            rel = path.relative_to(root).as_posix()
            for action, line in actions:
                if action not in recorded:
                    findings.append(
                        Finding(rel, line, "", f"review action #{action} has no record")
                    )
        listed = {action for action, _ in actions}
        for action in sorted(recorded - listed):
            findings.append(
                Finding(
                    log_rel,
                    _record_line(log_text, stem, action),
                    "",
                    f"{stem} action #{action} is recorded but the review has no such action",
                )
            )
    return findings


#: The markers README's "Not a licence to deploy" carries the published routing bar between.
BAR_BEGIN = "<!-- routing-bar:begin -->"
BAR_END = "<!-- routing-bar:end -->"
BAR_PAGE = "README.md"


def published_bar() -> str:
    """``RoutingPolicy.describe()`` of the checkout this script belongs to (ADR-0025 item 10)."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from crb.core.routing import DEFAULT_POLICY  # noqa: PLC0415 — src/ joins the path above

    return DEFAULT_POLICY.describe()


def check_routing_bar(root: Path, bar: str | None = None) -> list[Finding]:
    """README's routing bar is the code's, byte for byte once line wrapping is undone: the text
    between :data:`BAR_BEGIN` and :data:`BAR_END` must equal ``RoutingPolicy.describe()``
    (ADR-0025 item 10). The class of defect — the published bar drifting from the code's —
    gets a gate, not a sentence (docs/PREVENTION.md P-311)."""
    path = root / BAR_PAGE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if BAR_BEGIN not in text or BAR_END not in text:
        return [Finding(BAR_PAGE, 0, "", "no routing-bar markers: README must carry the bar")]
    line = text[: text.index(BAR_BEGIN)].count("\n") + 1
    inside = text.split(BAR_BEGIN, 1)[1].split(BAR_END, 1)[0]
    got = " ".join(inside.split())
    want = " ".join((bar if bar is not None else published_bar()).split())
    if got != want:
        return [
            Finding(
                BAR_PAGE,
                line,
                got[:120],
                "the routing bar differs from RoutingPolicy.describe() — regenerate it",
            )
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true", help="exit non-zero on any finding (CI)")
    ap.add_argument(
        "--root", default=None, help="the tree to read (the tests point this at a copy)"
    )
    ap.add_argument(
        "--allow",
        action="append",
        default=None,
        help="a page to read instead of ALLOWLIST (repeatable; the tests use it)",
    )
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    allow = tuple(args.allow) if args.allow else ALLOWLIST
    pages = tuple(args.allow) if args.allow else PROMISE_PAGES
    findings = (
        check_tree(root, allow)
        + check_review_actions(root)
        + check_promises(root, pages)
        + check_conformity(root, tuple(args.allow) if args.allow else None)
        + check_rows(root, tuple(p for p in pages if p in ROWS_PAGES))
    )
    if not args.allow:  # the gate's own run: README carries the code's bar
        findings += check_routing_bar(root)
    stream = sys.stderr if args.check else sys.stdout
    for f in findings:
        where = f"{f.path}:{f.line}" if f.line else f.path
        print(f"{where}: {f.reason}" + (f" — {f.sentence}" if f.sentence else ""), file=stream)
    print(
        f"{len(findings)} claim(s) without their evidence across "
        f"{len(expand(root, allow)[0])} page(s); {len(ALLOWLIST)} entries on the allowlist",
        file=stream,
    )
    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
