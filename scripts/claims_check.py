#!/usr/bin/env python3
"""The claim-tag gate — a quantified sentence on a public page carries its tag, or CI fails.

``docs/EVIDENCE-AND-CLAIMS.md`` §1 says every claim in this repository carries one tag:
``[measured]`` (with its ``n``, its method and the apparatus that produced it),
``[hypothesis]``, ``[aspiration]`` or ``[gap]``. Until this script that rule was prose, so
two claims on ``main`` were wrong for weeks and a reader found them, not a gate. This is the
gate: it reads the pages on ``ALLOWLIST``, finds the sentences that quantify something, and
fails when one carries no tag — or when a ``[measured]`` one does not carry what the tag
requires.

    python scripts/claims_check.py            # report what is untagged
    python scripts/claims_check.py --check    # CI: exit non-zero on any finding

**The heuristic, honestly.** A sentence is treated as a claim when, after inline code, links
and HTML comments are stripped, it contains either a percentage or a cardinal (``12``,
``1200``, ``eleven``) qualifying a plural noun — "eleven jobs", "22 tasks", "1200 tasks",
"four public libraries". A tag covers the block it sits in (a paragraph, a list item, a
blockquote paragraph), and a list item is also covered by the paragraph that introduces the
list, which is how the README tags a whole measured section at its head. Inline code is
stripped from the cover too: a page that *documents* ``[hypothesis]`` in backticks has not
thereby tagged the sentence around it.

**What it deliberately does not catch**, so nobody reads a green job as more than it is:

- *unquantified* claims — "the fastest", "secure by design", "proves correctness" — which are
  exactly the claims §7 forbids; a reader still has to read;
- claims inside tables, headings, fenced code, checklist items and a sentence that ends in a
  colon to introduce the thing it counts (the list below it is its own evidence);
- a percentage that is itself the confidence level ("Wilson 95% interval", "95% CI") — a
  result standing beside one ("65% passed (Wilson 95% interval)") *is* caught — a four-digit
  year, and a number written with a leading zero, which is an identifier ("ADR-0011");
- whether the tag is the *right* one, and whether a ``[measured]`` figure is true: it checks
  that ``n``, a method and an apparatus version are *present*, never that they are sound.
  Only a person reading the ledger can do that;
- any file not on ``ALLOWLIST``: everything else in ``docs/``, the reviews and the book are
  ungated, and the gap analysis says so.

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

**How a file opts in.** Add its repository-relative path to ``ALLOWLIST`` below and make it
pass in the same change. The list only grows: a page that has been cleaned never leaves it,
because leaving is how a gate quietly stops gating.

Navigation
----------
What it is:   The claim-tag gate over the public pages (stdlib only; CI's ``claims`` job).
What it does: Parses each allowlisted Markdown page into blocks, finds quantified sentences,
              and reports any that carry no permitted tag — and any ``[measured]`` tag
              without an n, a method or an apparatus version; reports every numbered action
              in a review's Actions table that has no stated record in the decision log,
              and every record whose review no longer lists the action or is no longer on
              disk; --check exits non-zero.
How:          Split the page into blocks (skipping headings, tables, fenced code) → keep the
              paragraph that introduces a list as the item's cover → strip code, links and
              comments → split into sentences → test each for a percentage or a cardinal
              qualifying a plural noun → look for a permitted tag in the block's cover. Then
              each docs/reviews/**/*.md Actions table (fenced examples skipped) and each review
              the log names → its action numbers ⇄ the records in
              docs/DECISION-LOG.md, each under a head that names the review's stem in
              backticks, then ``action #N: <state>``.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/EVIDENCE-AND-CLAIMS.md (the claim-tag rule it enforces the shape of),
              README.md, docs/RELEASING.md and docs/SUMMARY.md (the pages on the allowlist),
              docs/DECISION-LOG.md (where a review action's record lives),
              docs/reviews/2026-09-13-critical-friend.md (the review whose actions it holds),
              .github/workflows/ci.yml (the claims job that runs --check),
              scripts/code_map.py (the same gate idiom: parse, validate, --check)
Tested by:    tests/test_claims_check.py
Touch when:   a tag is added to the policy (update TAGS and EVIDENCE-AND-CLAIMS §1 together);
              a page joins the allowlist (add it and make it pass in the same change).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The pages this gate reads. It only grows (see the module docstring).
ALLOWLIST: tuple[str, ...] = (
    "README.md",
    "docs/RELEASING.md",
    "docs/SUMMARY.md",
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
_PERCENT = r"\d[\d,]*(?:\.\d+)?\s?%"
_PERCENT_RE = re.compile(_PERCENT)
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
    rf"|\bconfidence\s+(?:of|at|is|was)\s+{_PERCENT}",
    re.I,
)
_TAG_RE = re.compile(r"\[(" + "|".join(TAGS) + r")\b([^\]]*)\]", re.I)
_N_RE = re.compile(r"\bn\s*(?:=|≥|>=|of)\s*\d|\b\d[\d,]*\s*(?:/|of)\s*\d", re.I)
_APPARATUS_RE = re.compile(r"apparatus\s+(?:\d+\.\d+|n/a|none|[a-z0-9.-]+)", re.I)
_CODE_RE = re.compile(r"`[^`]*`")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
#: A fence line: its run of backticks or tildes (three or more), then whatever follows it.
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_CHECKLIST_RE = re.compile(r"^\s*[-*+]\s+\[[ xX]\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
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


def _strip_markup(text: str) -> str:
    """Inline code, link targets and HTML comments carry no claims of their own."""
    text = _COMMENT_RE.sub(" ", text)
    text = _CODE_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    return text.replace("**", "").replace("*", "").replace("> ", " ")


def _lines_with_fences(text: str) -> Iterator[tuple[int, str, bool]]:
    """``(line number, line, fenced)`` for every line; ``fenced`` is true for a fence's own
    delimiters and everything between them. A fence closes only on the marker that opened it
    (a ``~~~`` inside a backtick fence is content), as CommonMark reads it: the closing line
    is the opener's character, at least as many of them, and nothing after it — so
    ```` ```text ```` and a shorter run inside a longer fence are content (PR #54 review).
    Every reader of a page's structure goes through here, so a fenced example is never read
    as prose or as a review's action."""
    marker = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        m = _FENCE_RE.match(line)
        if m and not marker:
            marker = m.group(1)
            yield number, line, True
        elif (
            m
            and m.group(1)[0] == marker[0]
            and len(m.group(1)) >= len(marker)
            and not m.group(2).strip()
        ):
            marker = ""
            yield number, line, True
        else:
            yield number, line, bool(marker)


def blocks_of(text: str) -> list[Block]:
    """The page's prose blocks, each with the text that may tag it.

    Headings, table rows, fenced code and checklist items are not prose and are skipped. A
    list item's cover is its own text plus the paragraph that introduced the list.
    """
    out: list[Block] = []
    paragraph: list[str] = []
    start = 0
    intro = ""
    item: list[str] = []
    item_start = 0

    def close_paragraph() -> None:
        nonlocal paragraph, intro
        if paragraph:
            intro = " ".join(paragraph)
            out.append(Block(start, intro, intro))
            paragraph = []

    def close_item() -> None:
        nonlocal item
        if item:
            body = " ".join(item)
            out.append(Block(item_start, body, f"{intro} {body}"))
            item = []

    for number, line, fenced in _lines_with_fences(text):
        if fenced:
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
            continue
        if _CHECKLIST_RE.match(quoted):
            close_paragraph()
            close_item()
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


def is_claim(sentence: str) -> bool:
    """True when the sentence quantifies something (see the module docstring)."""
    text = _strip_markup(sentence).strip()
    if not text or text.endswith(":"):
        return False
    confidence = [m.span() for m in _CONFIDENCE_PERCENT_RE.finditer(text)]
    for match in _PERCENT_RE.finditer(text):
        if not any(start <= match.start() < end for start, end in confidence):
            return True
    for match in _COUNT_RE.finditer(text):
        cardinal, between, noun = match.group(1), match.group(2), match.group(3)
        if between and between.lower() in FUNCTION_WORDS:
            continue
        if noun.lower() in STRUCTURAL or noun.lower() in FUNCTION_WORDS:
            continue
        digits = cardinal.replace(",", "")
        if digits.replace(".", "").isdigit():
            if digits.startswith("0") and not digits.startswith("0."):
                continue  # "ADR-0011", "DL-0052" — an identifier, not a count
            value = float(digits)
            if value <= 1 or (value.is_integer() and 1900 <= value <= 2099):
                continue
        return True
    return False


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
        defects = tag_defects(block.cover)
        reasons = ["no claim tag"] if defects is None else defects
        for reason in reasons:
            findings.append(Finding(rel, block.line, claims[0].strip(), reason))
    return findings


def check_tree(root: Path, allow: tuple[str, ...]) -> list[Finding]:
    """Every finding across the allowlisted pages of ``root``."""
    findings: list[Finding] = []
    for rel in allow:
        path = root / rel
        if not path.is_file():
            findings.append(Finding(rel, 0, "", "on the allowlist but absent"))
            continue
        findings.extend(check_text(rel, path.read_text(encoding="utf-8")))
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
    findings = check_tree(root, allow) + check_review_actions(root)
    stream = sys.stderr if args.check else sys.stdout
    for f in findings:
        where = f"{f.path}:{f.line}" if f.line else f.path
        print(f"{where}: {f.reason}" + (f" — {f.sentence}" if f.sentence else ""), file=stream)
    print(
        f"{len(findings)} claim(s) without their evidence across {len(allow)} page(s)"
        f"; {len(ALLOWLIST)} page(s) on the allowlist, the rest of the documentation is ungated",
        file=stream,
    )
    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
