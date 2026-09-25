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

**How a file opts in.** Add its repository-relative path to ``ALLOWLIST`` below and make it
pass in the same change. The list only grows: a page that has been cleaned never leaves it,
because leaving is how a gate quietly stops gating.

Navigation
----------
What it is:   The claim-tag gate over the public pages (stdlib only; CI's ``claims`` job).
What it does: Parses each allowlisted Markdown page into blocks, finds quantified sentences,
              and reports any that carry no permitted tag — and any ``[measured]`` tag
              without an n, a method or an apparatus version; --check exits non-zero.
How:          Split the page into blocks (skipping headings, tables, fenced code) → keep the
              paragraph that introduces a list as the item's cover → strip code, links and
              comments → split into sentences → test each for a percentage or a cardinal
              qualifying a plural noun → look for a permitted tag in the block's cover.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/EVIDENCE-AND-CLAIMS.md (the claim-tag rule it enforces the shape of),
              README.md, docs/RELEASING.md and docs/reviews/2026-09-25-value-baseline.md (the
              pages on the allowlist),
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
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The pages this gate reads. It only grows (see the module docstring).
ALLOWLIST: tuple[str, ...] = (
    "README.md",
    "docs/RELEASING.md",
    "docs/reviews/2026-09-25-value-baseline.md",
)

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
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
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


def blocks_of(text: str) -> list[Block]:
    """The page's prose blocks, each with the text that may tag it.

    Headings, table rows, fenced code and checklist items are not prose and are skipped. A
    list item's cover is its own text plus the paragraph that introduced the list.
    """
    out: list[Block] = []
    fenced = False
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

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if _FENCE_RE.match(line):
            close_paragraph()
            close_item()
            fenced = not fenced
            continue
        if fenced:
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
    findings = check_tree(root, allow)
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
