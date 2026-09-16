"""Text-level mutator for C-family syntax — Go, JavaScript/TypeScript, Java/Kotlin, Rust.

The Python mutator reasons over an AST. No such parser ships in the standard library
for the other languages the bench grades, and ``crb.core`` takes no dependency, so
this family attacks the oracle at the **token** level instead: a small hand-written
scanner per language (a comment/string state machine plus longest-match operators)
finds the tokens on the task's changed lines, and every mutant is one exact-token
substitution, one condition wrapped in ``!( )``, or one whole single-line statement
blanked. It keeps the SAME operator taxonomy and the same determinism guarantees as
the AST mutator so a per-cell strength is comparable across languages *within a
language*:

* ``cmp_flip``     ``==``↔``!=`` (``===``↔``!==``), ``<``↔``<=``, ``>``↔``>=``
* ``arith_flip``   ``+``↔``-``, ``*``↔``/`` (binary occurrences only)
* ``bool_flip``    ``&&``↔``||``, ``true``↔``false``, ``!x`` → ``x``
* ``negate_cond``  ``if (cond)`` / ``if cond {`` → ``if (!(cond))`` / ``if !(cond) {``
* ``off_by_one``   every decimal integer literal ``n`` → ``n+1`` (suffix kept)
* ``return_value`` ``return true``↔``false``; ``return n`` nudged; ``return nil/null``
  and anything else untyped is skipped (the mutator never reasons about types)
* ``delete_stmt``  one single-line statement on a changed line blanked (never a line
  that opens/closes a block, a declaration clause, or a continuation)

What it cannot see (recorded in the provenance stamp as ``family="text"``): types,
so a swap that no longer type-checks is emitted and the *scorer* excludes it when the
toolchain rejects it (``outcome=uncompilable``, never a kill); function spans, so it
mutates exactly the changed lines rather than the changed functions; Rust tail
expressions (no ``return`` keyword) and ``if let`` (not negatable).

Honesty properties (correct-by-construction, same as the AST mutator)
--------------------------------------------------------------------
* **No randomness.** Candidates sort on ``(line, col, operator-rank, description)``;
  ids are assigned before truncation so a bounded list is a stable prefix.
* **Literals and comments are never touched.** The scanner emits them as opaque
  tokens; no operator looks inside a string, char, template, regex or comment.
* **Every mutant is structurally well-formed.** It re-tokenises (no unterminated
  literal or comment) and its brackets still balance — the text-level analogue of the
  AST mutator's ``compile()`` check. Type errors are the toolchain's to reject.
* **Every mutant differs from the source** and duplicates are dropped by content.

Standard library only (``re`` + a state machine); no I/O.

Navigation
----------
What it is:   The token-level mutator family (``TextLineMutator``) for Go, JavaScript/
              TypeScript, Java/Kotlin and Rust, with its per-language scanner and profiles.
What it does: Generates deterministic, bounded, structurally well-formed mutants on exactly the
              changed lines of a source file using the same seven-operator taxonomy as the
              AST family; never looks inside a literal or comment; never reasons about types
              (the toolchain rejects, the scorer excludes).
How:          ``tokenize`` (comment/string state machine + longest-match operators) →
              ``_collect`` (one candidate per eligible token or statement) → sort on
              ``(line, col, rank, description)`` → splice → re-scan and bracket-balance check →
              de-duplicate → stable prefix of ``max_mutants``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0009-text-level-mutators.md
Works with:   src/crb/core/oracle/mutant.py (the contract it implements),
              src/crb/core/oracle/mutation.py (registers it per language and scores its
              output; marks toolchain-rejected mutants ``uncompilable``),
              src/crb/core/spec.py (the ``Language`` values that key ``PROFILES``)
Tested by:    tests/test_oracle_mutation_text.py
Touch when:   never for a new repository; a new C-family language is one ``LanguageProfile``
              entry in ``PROFILES`` plus a pure-scanner test; a new operator or a changed
              substitution table changes ``describe()`` — the operator-set hash — so bump
              ``TEXT_MUTATION_VERSION`` and note it in docs/EVIDENCE-AND-CLAIMS.md.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Set
from dataclasses import dataclass
from typing import Any

from crb.core.oracle.mutant import DEFAULT_MAX_MUTANTS, Mutant

TEXT_MUTATION_VERSION = "mutation.text.v1"
MUTATOR_FAMILY_TEXT = "text"

LANG_GO = "go"
LANG_JAVASCRIPT = "javascript"
LANG_JVM = "jvm"
LANG_RUST = "rust"
TEXT_LANGUAGES: tuple[str, ...] = (LANG_GO, LANG_JAVASCRIPT, LANG_JVM, LANG_RUST)

# ---------------------------------------------------------------------------
# The operator table (fixed; hashed into the provenance stamp via describe())
# ---------------------------------------------------------------------------

OP_CMP_FLIP = "cmp_flip"
OP_ARITH_FLIP = "arith_flip"
OP_BOOL_FLIP = "bool_flip"
OP_NEGATE_COND = "negate_cond"
OP_OFF_BY_ONE = "off_by_one"
OP_RETURN_VALUE = "return_value"
OP_DELETE_STMT = "delete_stmt"

#: operator name → deterministic tie-break rank (sort is (line, col, rank, description)).
#: The five shared names carry the SAME ranks as the AST table.
_OP_RANK: dict[str, int] = {
    OP_CMP_FLIP: 0,
    OP_ARITH_FLIP: 1,
    OP_BOOL_FLIP: 2,
    OP_NEGATE_COND: 3,
    OP_OFF_BY_ONE: 4,
    OP_RETURN_VALUE: 5,
    OP_DELETE_STMT: 6,
}
TEXT_OPERATORS: tuple[str, ...] = tuple(sorted(_OP_RANK, key=_OP_RANK.__getitem__))

_ARITH_FLIPS: dict[str, str] = {"+": "-", "-": "+", "*": "/", "/": "*"}
_CMP_FLIPS: dict[str, str] = {
    "==": "!=",
    "!=": "==",
    "===": "!==",
    "!==": "===",
    "<": "<=",
    "<=": "<",
    ">": ">=",
    ">=": ">",
}
_BOOL_FLIPS: dict[str, str] = {"&&": "||", "||": "&&", "true": "false", "false": "true"}

# ---------------------------------------------------------------------------
# Language profiles: what the scanner and the statement rule need to know
# ---------------------------------------------------------------------------

#: Meaning of a single-quote literal per language.
QUOTE_STRING = "string"  # JS: 'text'
QUOTE_CHAR = "char"  # Go rune / Java char: 'x', '\n'
QUOTE_CHAR_OR_LIFETIME = "char_or_lifetime"  # Rust: 'x' or 'a (lifetime)

#: Meaning of a backtick literal per language.
BACKTICK_NONE = "none"
BACKTICK_RAW = "raw"  # Go raw string
BACKTICK_TEMPLATE = "template"  # JS template literal (with ${...})


@dataclass(frozen=True)
class LanguageProfile:
    """The per-language facts the scanner and the statement rule depend on."""

    language: str
    suffixes: tuple[str, ...]
    #: ``if cond {`` (Go/Rust) vs ``if (cond)`` (JS/Java).
    braces_condition: bool
    #: statements end with ``;`` (JS/Java/Rust) vs newline-terminated (Go).
    semicolons: bool
    single_quote: str
    backtick: str
    #: the language's "no value" words — a ``return`` of one is never mutated.
    null_words: tuple[str, ...]
    regex_literals: bool = False
    nested_block_comments: bool = False
    raw_strings: bool = False  # Rust r"…", r#"…"#, b"…", br"…"
    text_blocks: bool = False  # Java \"\"\"…\"\"\"
    leading_dot_float: bool = False  # ``.5`` is a number (JS/Java) — not in Go/Rust
    #: a line whose FIRST token is one of these is a declaration/clause, not a statement.
    stmt_skip_words: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Every field, in a fixed order — part of the operator-set hash via ``describe()``."""
        return {
            "language": self.language,
            "suffixes": list(self.suffixes),
            "braces_condition": self.braces_condition,
            "semicolons": self.semicolons,
            "single_quote": self.single_quote,
            "backtick": self.backtick,
            "null_words": list(self.null_words),
            "regex_literals": self.regex_literals,
            "nested_block_comments": self.nested_block_comments,
            "raw_strings": self.raw_strings,
            "text_blocks": self.text_blocks,
            "leading_dot_float": self.leading_dot_float,
            "stmt_skip_words": list(self.stmt_skip_words),
        }


_COMMON_SKIP: tuple[str, ...] = ("package", "import", "case", "default", "else", "type")

PROFILES: dict[str, LanguageProfile] = {
    LANG_GO: LanguageProfile(
        language=LANG_GO,
        suffixes=(".go",),
        braces_condition=True,
        semicolons=False,
        single_quote=QUOTE_CHAR,
        backtick=BACKTICK_RAW,
        null_words=("nil",),
        stmt_skip_words=(*_COMMON_SKIP, "func", "const", "var"),
    ),
    LANG_JAVASCRIPT: LanguageProfile(
        language=LANG_JAVASCRIPT,
        suffixes=(".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"),
        braces_condition=False,
        semicolons=True,
        single_quote=QUOTE_STRING,
        backtick=BACKTICK_TEMPLATE,
        null_words=("null", "undefined"),
        regex_literals=True,
        leading_dot_float=True,
        stmt_skip_words=(*_COMMON_SKIP, "export", "declare", "interface", "namespace"),
    ),
    LANG_JVM: LanguageProfile(
        language=LANG_JVM,
        suffixes=(".java", ".kt", ".kts"),
        braces_condition=False,
        semicolons=True,
        single_quote=QUOTE_CHAR,
        backtick=BACKTICK_NONE,
        null_words=("null",),
        text_blocks=True,
        leading_dot_float=True,
        stmt_skip_words=(*_COMMON_SKIP, "private", "public", "protected", "abstract", "class"),
    ),
    LANG_RUST: LanguageProfile(
        language=LANG_RUST,
        suffixes=(".rs",),
        braces_condition=True,
        semicolons=True,
        single_quote=QUOTE_CHAR_OR_LIFETIME,
        backtick=BACKTICK_NONE,
        null_words=("None",),
        nested_block_comments=True,
        raw_strings=True,
        stmt_skip_words=(*_COMMON_SKIP, "use", "mod", "pub", "extern", "impl", "fn", "struct"),
    ),
}

# ---------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------

KIND_ID = "id"
KIND_NUM = "num"
KIND_OP = "op"
KIND_PUNCT = "punct"
KIND_STR = "str"  # string / char / template / regex literal — opaque
KIND_COMMENT = "comment"


@dataclass(frozen=True)
class Token:
    """One lexeme with its position. Offsets are CHARACTERS (the mutator splices ``str``),
    unlike the AST family's byte offsets."""

    kind: str
    text: str
    line: int  # 1-based
    col: int  # 0-based, characters
    start: int  # absolute character offset

    @property
    def end(self) -> int:
        """Character offset just past the token."""
        return self.start + len(self.text)


class ScanError(ValueError):
    """The source is not scannable (unterminated literal or comment)."""


#: Longest-match first. Union over the four languages; a token that a language does
#: not have simply never appears in well-formed source of that language.
_OPERATORS: tuple[str, ...] = tuple(
    sorted(
        {
            ">>>=",
            "...",
            "<<=",
            ">>=",
            ">>>",
            "**=",
            "&&=",
            "||=",
            "??=",
            "===",
            "!==",
            "..=",
            "&^=",
            "->",
            "=>",
            "==",
            "!=",
            "<=",
            ">=",
            "&&",
            "||",
            "++",
            "--",
            "+=",
            "-=",
            "*=",
            "/=",
            "%=",
            "&=",
            "|=",
            "^=",
            "<<",
            ">>",
            "**",
            "??",
            "?.",
            "::",
            "..",
            ":=",
            "<-",
            "&^",
            "+",
            "-",
            "*",
            "/",
            "%",
            "=",
            "<",
            ">",
            "!",
            "&",
            "|",
            "^",
            "~",
            "?",
            ":",
        },
        key=lambda s: (-len(s), s),
    )
)
_PUNCT = "()[]{},;.@#"
_OPEN = "([{"
_CLOSE = ")]}"
_PAIR = {")": "(", "]": "[", "}": "{"}

_IDENT_RE = re.compile(r"(?:[^\W\d]|\$)[\w$]*")
_NUM_RE = re.compile(
    r"0[xX][0-9a-fA-F_]+[A-Za-z0-9_]*"
    r"|0[bB][01_]+[A-Za-z0-9_]*"
    r"|0[oO][0-7_]+[A-Za-z0-9_]*"
    r"|\d[\d_]*\.\d[\d_]*(?:[eE][+-]?\d+)?[A-Za-z0-9_]*"
    r"|\d[\d_]*[eE][+-]?\d+[A-Za-z0-9_]*"
    r"|\d[\d_]*[A-Za-z0-9_]*"
)
_LEADING_DOT_FLOAT_RE = re.compile(r"\.\d[\d_]*(?:[eE][+-]?\d+)?[A-Za-z0-9_]*")
#: A decimal integer literal: digits then an optional type suffix (``5u32``, ``10L``, ``7n``).
_INT_RE = re.compile(r"(\d+)([A-Za-z_][A-Za-z0-9_]*)?")

#: Words after which a ``/`` starts a regex literal in JavaScript.
_JS_REGEX_PREV_WORDS = frozenset(
    {
        "return",
        "typeof",
        "case",
        "in",
        "of",
        "delete",
        "void",
        "throw",
        "new",
        "instanceof",
        "do",
        "else",
        "yield",
        "await",
    }
)
#: Identifiers that are keywords, never operands (a ``-`` after one is unary).
_KEYWORDS_NOT_OPERANDS = frozenset(
    {
        *_JS_REGEX_PREV_WORDS,
        "if",
        "while",
        "for",
        "switch",
        "match",
        "go",
        "defer",
        "range",
        "as",
        "let",
        "const",
        "var",
        "mut",
        "fn",
        "func",
        "assert",
        "not",
        "and",
        "or",
    }
)


def _scan_quoted(src: str, i: int, quote: str, *, escapes: bool = True) -> int:
    """Index just past the closing ``quote`` starting at ``src[i] == quote``."""
    j = i + 1
    n = len(src)
    while j < n:
        c = src[j]
        if escapes and c == "\\":
            j += 2
            continue
        if c == quote:
            return j + 1
        j += 1
    raise ScanError(f"unterminated {quote!r} literal at offset {i}")


def _scan_delimited(src: str, i: int, opener: str, closer: str) -> int:
    """Index just past ``closer`` for a literal opened by ``opener`` at ``i`` (no escapes)."""
    j = src.find(closer, i + len(opener))
    if j < 0:
        raise ScanError(f"unterminated {opener!r} literal at offset {i}")
    return j + len(closer)


def _scan_template(src: str, i: int) -> int:
    """JS template literal starting at the backtick: escapes and nested ``${…}``."""
    j = i + 1
    n = len(src)
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "`":
            return j + 1
        if c == "$" and j + 1 < n and src[j + 1] == "{":
            j = _scan_template_expr(src, j + 2)
            continue
        j += 1
    raise ScanError(f"unterminated template literal at offset {i}")


def _scan_template_expr(src: str, i: int) -> int:
    """Index just past the ``}`` closing a ``${`` expression that starts at ``i``."""
    depth = 1
    j = i
    n = len(src)
    while j < n:
        c = src[j]
        if c in "\"'":
            j = _scan_quoted(src, j, c)
            continue
        if c == "`":
            j = _scan_template(src, j)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ScanError(f"unterminated template expression at offset {i}")


def _scan_block_comment(src: str, i: int, *, nested: bool) -> int:
    """Index just past ``*/`` for a ``/*`` at ``i``; Rust nests, the others do not."""
    depth = 1
    j = i + 2
    n = len(src)
    while j < n:
        if src.startswith("*/", j):
            depth -= 1
            j += 2
            if depth == 0:
                return j
            continue
        if nested and src.startswith("/*", j):
            depth += 1
            j += 2
            continue
        j += 1
    raise ScanError(f"unterminated block comment at offset {i}")


def _scan_regex(src: str, i: int) -> int:
    """JS regex literal at ``src[i] == '/'``: past the closing ``/`` and its flags."""
    j = i + 1
    n = len(src)
    in_class = False
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "\n":
            break
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            return j
        j += 1
    raise ScanError(f"unterminated regex literal at offset {i}")


def _scan_raw_string(src: str, i: int) -> int | None:
    """Rust ``r"…"`` / ``r#"…"#`` starting at the ``r``; ``None`` if not a raw string."""
    j = i + 1
    hashes = 0
    while j < len(src) and src[j] == "#":
        hashes += 1
        j += 1
    if j >= len(src) or src[j] != '"':
        return None
    closer = '"' + "#" * hashes
    k = src.find(closer, j + 1)
    if k < 0:
        raise ScanError(f"unterminated raw string at offset {i}")
    return k + len(closer)


def _regex_allowed_here(prev: Token | None) -> bool:
    """JS: a ``/`` begins a regex only where an operand cannot have just ended (else it
    is division). Same rule as a parser's "previous significant token" test."""
    if prev is None:
        return True
    if prev.kind == KIND_OP:
        return True
    if prev.kind == KIND_PUNCT:
        return prev.text in "([{,;"
    return prev.kind == KIND_ID and prev.text in _JS_REGEX_PREV_WORDS


def tokenize(source: str, profile: LanguageProfile) -> list[Token]:
    """Scan ``source`` into tokens; strings, chars, templates, regexes and comments are
    single opaque tokens. Whitespace is dropped. Raises :class:`ScanError` on an
    unterminated literal or comment (the source is then not mutable)."""
    tokens: list[Token] = []
    i = 0
    n = len(source)
    line = 1
    line_start = 0

    def emit(kind: str, start: int, end: int) -> None:
        nonlocal line, line_start
        text = source[start:end]
        tokens.append(Token(kind, text, line, start - line_start, start))
        nl = text.count("\n")
        if nl:
            line += nl
            line_start = start + text.rfind("\n") + 1

    prev_sig: Token | None = None
    while i < n:
        c = source[i]
        if c == "\n":
            line += 1
            line_start = i + 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        # --- comments ---------------------------------------------------------
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
            emit(KIND_COMMENT, i, end)
            i = end
            continue
        if source.startswith("/*", i):
            end = _scan_block_comment(source, i, nested=profile.nested_block_comments)
            emit(KIND_COMMENT, i, end)
            i = end
            continue
        # --- string-like literals ---------------------------------------------
        if c == '"':
            if profile.text_blocks and source.startswith('"""', i):
                end = _scan_delimited(source, i, '"""', '"""')
            else:
                end = _scan_quoted(source, i, '"')
            emit(KIND_STR, i, end)
            prev_sig = tokens[-1]
            i = end
            continue
        if c == "'":
            end = _scan_single_quote(source, i, profile)
            kind = KIND_ID if source[i:end].count("'") == 1 else KIND_STR
            emit(kind, i, end)
            prev_sig = tokens[-1]
            i = end
            continue
        if c == "`" and profile.backtick != BACKTICK_NONE:
            end = (
                _scan_template(source, i)
                if profile.backtick == BACKTICK_TEMPLATE
                else _scan_delimited(source, i, "`", "`")
            )
            emit(KIND_STR, i, end)
            prev_sig = tokens[-1]
            i = end
            continue
        if c == "/" and profile.regex_literals and _regex_allowed_here(prev_sig):
            try:
                end = _scan_regex(source, i)
            except ScanError:
                end = -1  # not a regex after all: fall through to the operator scan
            if end > 0:
                emit(KIND_STR, i, end)
                prev_sig = tokens[-1]
                i = end
                continue
        # --- numbers ------------------------------------------------------------
        num = None
        if c.isdigit():
            num = _NUM_RE.match(source, i)
        elif c == "." and profile.leading_dot_float:
            num = _LEADING_DOT_FLOAT_RE.match(source, i)
        if num:
            emit(KIND_NUM, i, num.end())
            prev_sig = tokens[-1]
            i = num.end()
            continue
        # --- identifiers (incl. Rust raw strings / raw identifiers) --------------
        m = _IDENT_RE.match(source, i)
        if m:
            end = m.end()
            word = m.group(0)
            if (
                profile.raw_strings
                and word in {"r", "br", "cr"}
                and end < n
                and source[end] in '"#'
            ):
                raw_end = _scan_raw_string(source, end - 1)
                if raw_end is not None:
                    emit(KIND_STR, i, raw_end)
                    prev_sig = tokens[-1]
                    i = raw_end
                    continue
            if profile.raw_strings and word in {"b", "c"} and end < n and source[end] == '"':
                end = _scan_quoted(source, end, '"')
                emit(KIND_STR, i, end)
                prev_sig = tokens[-1]
                i = end
                continue
            if profile.raw_strings and word == "r" and source.startswith("#", end):
                m2 = _IDENT_RE.match(source, end + 1)
                if m2:
                    end = m2.end()
            emit(KIND_ID, i, end)
            prev_sig = tokens[-1]
            i = end
            continue
        # --- operators / punctuation --------------------------------------------
        for op in _OPERATORS:
            if source.startswith(op, i):
                emit(KIND_OP, i, i + len(op))
                prev_sig = tokens[-1]
                i += len(op)
                break
        else:
            emit(KIND_PUNCT, i, i + 1)  # brackets, separators, anything unknown
            prev_sig = tokens[-1]
            i += 1
    return tokens


def _scan_single_quote(src: str, i: int, profile: LanguageProfile) -> int:
    """Index past a single-quote literal: a string (JS), a char (Go/Java), or in Rust a
    char OR a lifetime (``'a`` — no closing quote; returned as an identifier)."""
    if profile.single_quote == QUOTE_STRING:
        return _scan_quoted(src, i, "'")
    if profile.single_quote == QUOTE_CHAR:
        return _scan_quoted(src, i, "'")
    # Rust: a char literal ('x', '\n', '\u{1F600}') or a lifetime ('a — no closing quote).
    n = len(src)
    if i + 1 < n and src[i + 1] == "\\":
        return _scan_quoted(src, i, "'")
    if i + 2 < n and src[i + 2] == "'":
        return i + 3
    m = _IDENT_RE.match(src, i + 1)
    if m:
        return m.end()
    return _scan_quoted(src, i, "'")


def brackets_balanced(tokens: list[Token]) -> bool:
    """Every ``( [ {`` closes with its own kind, in order, and nothing is left open."""
    stack: list[str] = []
    for t in tokens:
        if t.kind != KIND_PUNCT:
            continue
        if t.text in _OPEN:
            stack.append(t.text)
        elif t.text in _CLOSE:
            if not stack or stack[-1] != _PAIR[t.text]:
                return False
            stack.pop()
    return not stack


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------


#: add(token, op, description, start, end, replacement)
_AddFn = Callable[["Token", str, str, tuple[int, int], str], None]


@dataclass(frozen=True)
class _Candidate:
    """A splice (``source[start:end]`` → ``replacement``) before well-formedness and
    de-duplication; the id is assigned in ``generate``."""

    line: int
    col: int
    op: str
    description: str
    start: int
    end: int
    replacement: str

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """The total order that makes generation seed-free (same key as the AST family)."""
        return (self.line, self.col, _OP_RANK[self.op], self.description)


def _is_operand_end(tok: Token | None) -> bool:
    """Whether an expression just ended before this point (so the next ``-`` is binary)."""
    if tok is None:
        return False
    if tok.kind in (KIND_NUM, KIND_STR):
        return True
    if tok.kind == KIND_ID:
        return tok.text not in _KEYWORDS_NOT_OPERANDS
    return tok.kind == KIND_PUNCT and tok.text in ")]"


def _spaced(source: str, tok: Token) -> bool:
    """Whitespace on both sides — how a comparison ``<`` is told from a generic bracket."""
    before = source[tok.start - 1] if tok.start > 0 else " "
    after = source[tok.end] if tok.end < len(source) else " "
    return before.isspace() and after.isspace()


def _int_nudge(text: str) -> str | None:
    """``n`` → ``n+1`` keeping a type suffix; ``None`` when not a plain decimal int."""
    if text[:2].lower() in ("0x", "0b", "0o"):
        return None  # hex / binary / octal: not a decimal literal
    m = _INT_RE.fullmatch(text)
    if m is None:
        return None
    digits, suffix = m.group(1), m.group(2) or ""
    if len(digits) > 1 and digits[0] == "0":
        return None  # a legacy octal / invalid literal after the nudge
    if suffix and suffix[0] in "eE_":
        return None  # an exponent or a digit-group separator, not a type suffix
    return f"{int(digits) + 1}{suffix}"


class _LineIndex:
    """Tokens grouped by line, plus the lines swallowed by multi-line literals/comments."""

    def __init__(self, source: str, tokens: list[Token]) -> None:
        self.by_line: dict[int, list[Token]] = {}
        self.covered: set[int] = set()
        for t in tokens:
            self.by_line.setdefault(t.line, []).append(t)
            span = t.text.count("\n")
            if span:
                self.covered.update(range(t.line, t.line + span + 1))
        self.line_starts = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                self.line_starts.append(i + 1)
        self.source = source

    def span(self, line: int) -> tuple[int, int]:
        """Character span of ``line`` (1-based) EXCLUDING its newline."""
        s = self.line_starts[line - 1]
        e = self.line_starts[line] - 1 if line < len(self.line_starts) else len(self.source)
        return s, e


def _sig(tokens: list[Token], i: int, step: int) -> Token | None:
    """The nearest non-comment token from ``i`` (exclusive) in direction ``step``."""
    j = i + step
    while 0 <= j < len(tokens):
        if tokens[j].kind != KIND_COMMENT:
            return tokens[j]
        j += step
    return None


def _collect(
    source: str, tokens: list[Token], lines: Set[int], profile: LanguageProfile
) -> list[_Candidate]:
    """Every operator's candidates on the tokens of the changed lines, then one
    ``delete_stmt`` per deletable changed line. Unsorted; the caller orders them."""
    out: list[_Candidate] = []
    idx = _LineIndex(source, tokens)

    def add(tok: Token, op: str, desc: str, span: tuple[int, int], repl: str) -> None:
        out.append(_Candidate(tok.line, tok.col, op, desc, span[0], span[1], repl))

    for i, tok in enumerate(tokens):
        if tok.line not in lines or tok.kind in (KIND_STR, KIND_COMMENT):
            continue
        prev = _sig(tokens, i, -1)
        nxt = _sig(tokens, i, +1)

        if tok.kind == KIND_OP:
            if tok.text in _ARITH_FLIPS and _is_operand_end(prev):
                new = _ARITH_FLIPS[tok.text]
                add(tok, OP_ARITH_FLIP, f"{tok.text} -> {new}", (tok.start, tok.end), new)
            elif tok.text in _CMP_FLIPS:
                # `<`/`>` are also generic brackets (List<String>, Vec<i32>): only the
                # SPACED form is read as a comparison.
                if tok.text in ("<", ">") and not _spaced(source, tok):
                    continue
                new = _CMP_FLIPS[tok.text]
                add(tok, OP_CMP_FLIP, f"{tok.text} -> {new}", (tok.start, tok.end), new)
            elif tok.text in ("&&", "||"):
                if not _is_operand_end(prev):
                    continue  # Rust `|| expr` closure, not a boolean operator
                new = _BOOL_FLIPS[tok.text]
                add(tok, OP_BOOL_FLIP, f"{tok.text} -> {new}", (tok.start, tok.end), new)
            elif tok.text == "!":
                # `!x` → `x`; never a Rust macro bang (ident!), a TS non-null (x!), or `-> !`
                if _is_operand_end(prev) or (prev is not None and prev.text == "->"):
                    continue
                if nxt is None or not (
                    nxt.kind in (KIND_ID, KIND_NUM)
                    or (nxt.kind == KIND_PUNCT and nxt.text == "(")
                    or (nxt.kind == KIND_OP and nxt.text == "!")
                ):
                    continue
                add(tok, OP_BOOL_FLIP, "!x -> x", (tok.start, tok.end), "")
            continue

        if tok.kind == KIND_NUM:
            nudged = _int_nudge(tok.text)
            if nudged is not None:
                add(tok, OP_OFF_BY_ONE, f"{tok.text} -> {nudged}", (tok.start, tok.end), nudged)
            continue

        if tok.kind != KIND_ID:
            continue
        if tok.text in ("true", "false"):
            if prev is not None and prev.kind == KIND_PUNCT and prev.text == ".":
                continue
            new = _BOOL_FLIPS[tok.text]
            add(tok, OP_BOOL_FLIP, f"{tok.text} -> {new}", (tok.start, tok.end), new)
        elif tok.text == "return":
            _return_value(tokens, i, tok, add=add)
        elif tok.text == "if" and not (
            prev is not None and prev.kind == KIND_PUNCT and prev.text == "."
        ):
            _negate_condition(source, tokens, i, tok, profile=profile, add=add)

    for line in sorted(lines):
        _delete_statement(idx, line, profile, out)
    return out


def _return_value(tokens: list[Token], i: int, tok: Token, *, add: _AddFn) -> None:
    """``return <one token>`` → flipped/nudged; anything untyped is skipped."""
    rest: list[Token] = []
    for t in tokens[i + 1 :]:
        if t.line != tok.line or (t.kind == KIND_PUNCT and t.text in ";}"):
            break
        if t.kind != KIND_COMMENT:
            rest.append(t)
    if len(rest) != 1:
        return
    v = rest[0]
    if v.kind == KIND_ID and v.text in ("true", "false"):
        new = _BOOL_FLIPS[v.text]
    elif v.kind == KIND_NUM:
        nudged = _int_nudge(v.text)
        if nudged is None:
            return
        new = nudged
    else:
        return  # nil/null/None-like, or an expression the mutator cannot type
    add(tok, OP_RETURN_VALUE, f"return {v.text} -> return {new}", (v.start, v.end), new)


def _negate_condition(
    source: str, tokens: list[Token], i: int, tok: Token, *, profile: LanguageProfile, add: _AddFn
) -> None:
    """Wrap the condition of an ``if`` on ``tok``'s line in ``!( )``; single-line only, and
    never an ``if let`` (a pattern is not a boolean)."""
    same_line = [t for t in tokens[i + 1 :] if t.line == tok.line and t.kind != KIND_COMMENT]
    if not same_line:
        return
    if profile.braces_condition:
        # Go/Rust: `if [init;] cond {` — the block's `{` is the first depth-0 brace.
        depth = 0
        block: Token | None = None
        last_semi: Token | None = None
        for t in same_line:
            if t.kind != KIND_PUNCT:
                continue
            if t.text in "([":
                depth += 1
            elif t.text in ")]":
                depth -= 1
            elif t.text == "{" and depth == 0:
                block = t
                break
            elif t.text == ";" and depth == 0:
                last_semi = t
        if block is None:
            return
        start = last_semi.end if last_semi is not None else tok.end
        cond = source[start : block.start].strip()
        if not cond or cond.startswith("let ") or cond == "let":
            return
        cs = source.index(cond, start)
        add(tok, OP_NEGATE_COND, "if cond -> if !(cond)", (cs, cs + len(cond)), f"!({cond})")
        return
    # JS/Java: `if (cond)` — the matching `)` on the same line.
    opener = same_line[0]
    if not (opener.kind == KIND_PUNCT and opener.text == "("):
        return
    depth = 0
    closer: Token | None = None
    for t in same_line:
        if t.kind != KIND_PUNCT:
            continue
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
            if depth == 0:
                closer = t
                break
    if closer is None:
        return
    cond = source[opener.end : closer.start].strip()
    if not cond:
        return
    cs = source.index(cond, opener.end)
    add(tok, OP_NEGATE_COND, "if (cond) -> if (!(cond))", (cs, cs + len(cond)), f"!({cond})")


#: an OPERATOR that begins a line continues the previous statement (a leading `.`, `)`
#: or `}` is punctuation and is refused one check earlier).
_CONTINUATION_START = (
    "?",
    ":",
    "&&",
    "||",
    "+",
    "-",
    "*",
    "/",
    "=",
    "=>",
    "->",
)
_GO_CONTINUATION_END = (
    ",",
    "(",
    "[",
    "+",
    "-",
    "*",
    "/",
    "%",
    "=",
    "<",
    ">",
    "&",
    "|",
    "^",
    "!",
    ":",
    ".",
    ";",
    "&&",
    "||",
    ":=",
    "<-",
)


def _delete_statement(
    idx: _LineIndex, line: int, profile: LanguageProfile, out: list[_Candidate]
) -> None:
    """Blank one single-line statement. A block boundary, a declaration clause, a label,
    a directive or a continuation line is never a statement."""
    if line in idx.covered or line not in idx.by_line:
        return
    toks = [t for t in idx.by_line[line] if t.kind != KIND_COMMENT]
    if not toks:
        return
    first, last = toks[0], toks[-1]
    if any(t.kind == KIND_PUNCT and t.text in "{}" for t in toks):
        return
    if not brackets_balanced(toks):
        return
    if first.kind in (KIND_STR, KIND_PUNCT) and first.text not in ("(",):
        return  # a directive ("use strict"), an attribute (#[…]/@…), a closer, a `.` chain
    if first.kind == KIND_OP and first.text in _CONTINUATION_START:
        return
    if first.kind == KIND_ID and first.text in profile.stmt_skip_words:
        return
    if last.kind == KIND_OP and last.text == ":":
        return  # a label / case clause
    if profile.semicolons:
        if not (last.kind == KIND_PUNCT and last.text == ";"):
            return
    elif last.kind in (KIND_OP, KIND_PUNCT) and last.text in _GO_CONTINUATION_END:
        return
    s, e = idx.span(line)
    out.append(_Candidate(line, first.col, OP_DELETE_STMT, "statement deleted", s, e, ""))


# ---------------------------------------------------------------------------
# The mutator
# ---------------------------------------------------------------------------


class TextLineMutator:
    """The seven-operator token-level mutator for one C-family language.

    Same contract as :class:`~crb.core.oracle.mutation.PythonAstMutator`: pure,
    deterministic, bounded to a stable prefix, every mutant structurally well-formed
    and different from the source. Confined to EXACTLY the changed lines (a text
    mutator cannot see function spans).
    """

    family = MUTATOR_FAMILY_TEXT
    operators = TEXT_OPERATORS

    def __init__(self, language: str) -> None:
        key = language.strip().lower()
        if key not in PROFILES:
            raise ValueError(f"no text mutator profile for language {language!r}")
        self.language = key
        self.profile = PROFILES[key]
        self.suffixes: tuple[str, ...] = self.profile.suffixes

    def accepts(self, path: str) -> bool:
        """``True`` for a path with one of the profile's source suffixes."""
        return path.endswith(self.suffixes)

    def generate(
        self,
        source: str,
        changed_lines: Set[int],
        *,
        max_mutants: int = DEFAULT_MAX_MUTANTS,
        path: str = "<src>",
    ) -> list[Mutant]:
        """Deterministic, bounded token-level mutants on exactly the changed lines.

        Seed-free: candidates sort on ``(line, col, operator-rank, description)`` and
        ids are assigned on the FULL filtered list before truncation, so the bounded
        list is always a PREFIX of the unbounded one. An unscannable source (an
        unterminated literal/comment) yields no mutants, like an unparseable one.
        """
        try:
            tokens = tokenize(source, self.profile)
        except ScanError:
            return []
        # A source whose brackets already do not balance (the scanner's view) cannot be
        # held to the balance check on its mutants; only a balanced original gates.
        original_ok = brackets_balanced(tokens)
        candidates = sorted(
            _collect(source, tokens, changed_lines, self.profile), key=lambda c: c.sort_key
        )

        mutants: list[Mutant] = []
        seen: set[str] = set()
        for cand in candidates:
            mutated = source[: cand.start] + cand.replacement + source[cand.end :]
            if mutated == source or mutated in seen:
                continue
            if original_ok and not self._well_formed(mutated):
                continue
            seen.add(mutated)
            mutants.append(
                Mutant(
                    mutant_id=f"m{len(mutants) + 1:02d}_{cand.op}_L{cand.line}",
                    op=cand.op,
                    line=cand.line,
                    col=cand.col,
                    description=cand.description,
                    mutated_source=mutated,
                    path=path,
                )
            )
        return mutants[: max(0, max_mutants)]

    def _well_formed(self, mutated: str) -> bool:
        """Structural check: still scannable and brackets still balance."""
        try:
            return brackets_balanced(tokenize(mutated, self.profile))
        except ScanError:
            return False

    def describe(self) -> dict[str, Any]:
        """What the operator set IS — hashed into the provenance stamp. Includes the
        language and its profile, so the hash differs per language by construction."""
        return {
            "language": self.language,
            "mutator": type(self).__name__,
            "family": self.family,
            "version": TEXT_MUTATION_VERSION,
            "operators": [{"op": op, "rank": _OP_RANK[op]} for op in self.operators],
            "arith_flips": sorted(f"{a} -> {b}" for a, b in _ARITH_FLIPS.items()),
            "cmp_flips": sorted(f"{a} -> {b}" for a, b in _CMP_FLIPS.items()),
            "bool_flips": sorted(f"{a} -> {b}" for a, b in _BOOL_FLIPS.items()),
            "profile": self.profile.to_dict(),
        }


def text_mutators() -> dict[str, TextLineMutator]:
    """One mutator per supported language, keyed by the ``Language`` value."""
    return {lang: TextLineMutator(lang) for lang in TEXT_LANGUAGES}


__all__ = [
    "LANG_GO",
    "LANG_JAVASCRIPT",
    "LANG_JVM",
    "LANG_RUST",
    "MUTATOR_FAMILY_TEXT",
    "PROFILES",
    "TEXT_LANGUAGES",
    "TEXT_MUTATION_VERSION",
    "TEXT_OPERATORS",
    "LanguageProfile",
    "ScanError",
    "TextLineMutator",
    "Token",
    "brackets_balanced",
    "text_mutators",
    "tokenize",
]
