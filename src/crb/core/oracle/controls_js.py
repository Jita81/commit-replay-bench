"""Negative-control transforms for JavaScript / TypeScript — pure text, deterministic.

Like :mod:`crb.core.oracle.controls_go`, this module reads source through the token
scanner of :mod:`crb.core.oracle.mutators_text` (JavaScript profile: strings,
template literals, regex literals and comments are opaque) and never a grammar. The
four transforms, and what each honestly is:

* **stub** — every function-shaped unit the gold commit changed (``function f(…) {``,
  ``const f = (…) => {``, class/object methods, ``exports.f = function (…) {``)
  keeps its signature and its body becomes ``return undefined;``. Units the commit
  ADDS are appended with the gold signature and the same body, exported the way the
  gold exports them (``export function`` / ``module.exports.f = f``), so the target
  test fails on an *assertion*, never on a missing import. The caller syntax-checks
  the result (``node --check`` for ``.js/.mjs/.cjs``; the scanner's structural check
  for TypeScript/JSX, which node cannot parse): a stub that does not parse is
  ``not_constructible``.
* **regression** — the gold overlaid PLUS a top-level ``throw`` prepended to an
  adjacent module: one a test *inside the belt scope* imports and neither the target
  tests nor the module(s) under test import (relative specifiers resolved against
  the importing file). Under ``TARGET_ONLY`` there is no belt test outside the
  target, so the control can never be built — the reason names the scope.
* **hardcode_cheat** — literal ``(call, expectation)`` pairs parsed from the target
  test (``expect(f(1, 2)).toBe(3)`` / ``toEqual`` / ``toStrictEqual``,
  ``assert.equal|strictEqual|deepEqual|deepStrictEqual(f(1, 2), 3)``, ava/tape
  ``t.is|deepEqual|equal(f(1), 2)``) become ``if (a === 1 && b === 2) { return 3; }``
  guards at the top of the parent function — nothing implemented. A function the
  commit adds is appended with the GOLD signature and only the guards.
* **env_poison** — an identity edit to the source plus the runner's own
  *collection-time hook*: jest ``setupFiles`` (``package.json#jest`` merged, else a
  new ``jest.config.cjs``), mocha ``.mocharc.json#require``, vitest
  ``vitest.config.mjs#test.setupFiles`` + ``vi.mock``. The hook loads a gold copy
  written BESIDE the module under test (so its relative imports still resolve) and
  patches the real module's exports in place (CJS) or mocks the module id (ESM).
  ``node --test`` has no configuration file at all and ``NODE_OPTIONS`` belongs to
  the harness, so for that runner the vector honestly does not exist. An existing
  JS-format config the transform cannot merge textually is ``not_constructible``
  too — the poison is never guessed.

Every function here is pure over text (no I/O); the runner in
:mod:`crb.core.oracle.controls` writes the files and runs the syntax check. A
transform that cannot be built raises :class:`NotConstructible` with the reason.

Navigation
----------
What it is:   The JavaScript/TypeScript negative-control transforms — pure text functions over
              the shared scanner's tokens, a small parser for function-shaped units, and the
              per-runner env-poison planner.
What it does: Builds ``stub`` (``return undefined;`` bodies, gold export wiring),
              ``regression`` (a top-level ``throw`` in an adjacent belt-scope module),
              ``hardcode_cheat`` (literal guards from expect/assert/t assertions) and
              ``env_poison`` (the runner's own setup hook loading a gold copy) for one task;
              raises ``NotConstructible`` with the reason when a cheat cannot honestly be
              built — an existing JS-format config is never rewritten by guesswork.
How:          ``tokenize`` (JS profile) → ``js_functions`` (function/arrow/method units with
              exact spans) → splices last-first; ``js_imports`` resolves relative specifiers
              for the poison selector; ``env_poison_plan`` returns ``{path: text}`` per tool.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0010-polyglot-negative-controls.md, docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/oracle/controls.py (the I/O shell that dispatches here and runs
              ``node --check``), src/crb/core/oracle/mutators_text.py (the scanner and the
              JavaScript profile), src/crb/core/oracle/controls_go.py (the sibling family),
              src/crb/core/runners/node_runners.py (whose tool names key ``env_poison_plan``),
              src/crb/core/test_infra.py (the config files this writes are exactly what
              belt 1b disqualifies — the expected ``caught by belt 1``)
Tested by:    tests/test_oracle_controls_js.py
Touch when:   never for a new repository; a test framework whose assertions are not parsed
              (``_EXPECT_VERBS``/``_ASSERT_VERBS``/``_T_VERBS``) or a runner without a hook
              is extended here with a pure snippet test first; ``describe()`` is part of the
              apparatus stamp, so a changed transform is a ``CONTROLS_VERSION`` bump in
              src/crb/core/oracle/controls.py.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from crb.core.oracle.mutators_text import (
    KIND_COMMENT,
    KIND_ID,
    KIND_NUM,
    KIND_OP,
    KIND_PUNCT,
    KIND_STR,
    LANG_JAVASCRIPT,
    PROFILES,
    ScanError,
    Token,
    brackets_balanced,
    tokenize,
)

JS_PROFILE = PROFILES[LANG_JAVASCRIPT]

REGRESSION_POISON_MARK = "negctrl-regression-poison"
ENV_POISON_MARK = "negctrl-env-poison"
ENV_POISON_SETUP_CJS = "negctrl_env_poison.cjs"
ENV_POISON_SETUP_ESM = "negctrl_env_poison.mjs"
ENV_POISON_GOLD_SUFFIX = ".negctrl_env_poison_gold"

#: suffixes ``node --check`` can parse; anything else gets the structural check.
NODE_CHECKABLE: tuple[str, ...] = (".js", ".mjs", ".cjs")
JS_SUFFIXES: tuple[str, ...] = JS_PROFILE.suffixes

KIND_FUNCTION = "function"
KIND_ARROW = "arrow"
KIND_METHOD = "method"

_NOT_METHOD_NAMES = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "function",
        "return",
        "with",
        "do",
        "else",
        "try",
        "finally",
        "new",
        "typeof",
        "await",
        "yield",
        "class",
        "super",
        "import",
        "export",
        "throw",
        "delete",
        "void",
        "instanceof",
    }
)
_METHOD_PREV = frozenset({"{", "}", ";", ","})
_METHOD_MODIFIERS = frozenset({"async", "static", "get", "set"})
_LITERAL_WORDS = frozenset({"true", "false", "null", "undefined"})
_EXPECT_VERBS = frozenset({"toBe", "toEqual", "toStrictEqual"})
_ASSERT_VERBS = frozenset({"equal", "strictEqual", "deepEqual", "deepStrictEqual"})
_T_VERBS = frozenset({"is", "deepEqual", "equal", "strictEqual"})
_JEST_CONFIG_RE = re.compile(r"^jest\.config\.(js|cjs|mjs|ts|json)$")
_VITEST_CONFIG_RE = re.compile(r"^(vitest|vite)\.config\.(js|cjs|mjs|ts|mts|cts)$")
_MOCHARC_RE = re.compile(r"^\.mocharc(\.(js|cjs|mjs|yml|yaml|jsonc|json))?$")


class NotConstructible(ValueError):
    """The cheat cannot honestly be built for this task; ``str(exc)`` is the reason."""


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------


def sig_tokens(src: str) -> list[Token]:
    """Significant tokens (comments dropped). Raises :class:`ScanError`."""
    return [t for t in tokenize(src, JS_PROFILE) if t.kind != KIND_COMMENT]


def structurally_sound(src: str) -> bool:
    """The scanner's well-formedness check (re-scan + balanced brackets) — the
    syntax check for files ``node --check`` cannot parse."""
    try:
        return brackets_balanced(tokenize(src, JS_PROFILE))
    except ScanError:
        return False


def _is(tok: Token | None, text: str, kind: str | None = None) -> bool:
    """``tok`` exists and has this text (and kind, when given)."""
    return tok is not None and tok.text == text and (kind is None or tok.kind == kind)


def _at(toks: Sequence[Token], i: int) -> Token | None:
    """``toks[i]`` or ``None`` past either end — every lookahead goes through this."""
    return toks[i] if 0 <= i < len(toks) else None


_OPEN = {"(": ")", "[": "]", "{": "}"}


def _match(toks: Sequence[Token], i: int) -> int:
    """Index of the bracket token closing the one at ``i``; ``-1`` if unbalanced."""
    opener = toks[i].text
    closer = _OPEN[opener]
    depth = 0
    for j in range(i, len(toks)):
        t = toks[j]
        if t.kind != KIND_PUNCT:
            continue
        if t.text == opener:
            depth += 1
        elif t.text == closer:
            depth -= 1
            if depth == 0:
                return j
    return -1


def _split_commas(toks: Sequence[Token]) -> list[list[Token]]:
    """Split a token run on depth-0 commas (an argument or parameter list)."""
    out: list[list[Token]] = []
    cur: list[Token] = []
    depth = 0
    for t in toks:
        if t.kind == KIND_PUNCT and t.text in _OPEN:
            depth += 1
        elif t.kind == KIND_PUNCT and t.text in ")]}":
            depth -= 1
        if t.kind == KIND_PUNCT and t.text == "," and depth == 0:
            out.append(cur)
            cur = []
            continue
        cur.append(t)
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# function-shaped units
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JsFunc:
    """One function-shaped unit and its exact spans."""

    key: str  # ``name`` | ``Class.name``
    name: str
    kind: str  # KIND_FUNCTION | KIND_ARROW | KIND_METHOD
    start: int  # offset of the unit's first token (``function`` / ``async`` / name / ``(``)
    end: int  # just past the body ``}``
    body_open: int
    body_close: int
    params: tuple[str, ...]  # "" for a destructured / defaulted-non-identifier param
    params_text: str  # raw text between the parentheses
    exported: bool = False
    default_export: bool = False
    async_: bool = False
    generator: bool = False

    def segment(self, src: str) -> str:
        """The whole unit's text — what "changed by the commit" compares."""
        return src[self.start : self.end]


def _param_names(src: str, toks: Sequence[Token]) -> tuple[str, ...]:
    """Identifier per parameter; ``""`` for anything that is not a plain name
    (destructuring, defaults on non-identifiers). A rest ``...x`` and ``x = 1``
    still yield ``x``."""
    out: list[str] = []
    for elem in _split_commas(toks):
        if not elem:
            continue
        e = elem
        if _is(e[0], "...", KIND_OP):
            e = e[1:]
        if e and e[0].kind == KIND_ID and (len(e) == 1 or _is(_at(e, 1), "=", KIND_OP)):
            out.append(e[0].text)
        else:
            out.append("")
    return tuple(out)


def _assign_name(toks: Sequence[Token], i: int) -> tuple[str, int] | None:
    """For a unit whose token ``i`` is ``function`` / ``async`` / the params ``(``:
    the name given by ``const name =`` / ``exports.name =`` / ``name:`` just before
    it, and the offset index of that declaration's start. ``None`` if no such target."""
    j = i - 1
    t = _at(toks, j)
    if t is None:
        return None
    if _is(t, "=", KIND_OP) or _is(t, ":", KIND_OP):
        k = j - 1
        name_tok = _at(toks, k)
        if name_tok is None or name_tok.kind not in (KIND_ID, KIND_STR):
            return None
        name = name_tok.text.strip("'\"")
        start_idx = k
        # walk back over ``a.b.c`` chains and a ``const|let|var`` keyword
        while (
            _is(_at(toks, start_idx - 1), ".", KIND_PUNCT) and _at(toks, start_idx - 2) is not None
        ):
            start_idx -= 2
        prev = _at(toks, start_idx - 1)
        if prev is not None and prev.kind == KIND_ID and prev.text in ("const", "let", "var"):
            start_idx -= 1
        return name, start_idx
    return None


def js_functions(src: str) -> dict[str, JsFunc]:
    """Every function-shaped unit in ``src`` keyed ``name`` / ``Class.name``; the first
    definition of a key wins. Raises :class:`ScanError` on an unscannable source."""
    toks = sig_tokens(src)
    out: dict[str, JsFunc] = {}
    classes: list[tuple[str, int, int]] = []  # (name, open idx, close idx)

    def owner(idx: int) -> str:
        for name, o, c in reversed(classes):
            if o < idx < c:
                return name
        return ""

    i = 0
    while i < len(toks):
        t = toks[i]
        # class X { … }
        if t.kind == KIND_ID and t.text == "class":
            n = _at(toks, i + 1)
            j = i + 1
            cname = ""
            if n is not None and n.kind == KIND_ID:
                cname = n.text
                j += 1
            while j < len(toks) and not _is(toks[j], "{", KIND_PUNCT):
                j += 1
            if j < len(toks):
                c = _match(toks, j)
                if c > 0:
                    classes.append((cname or "(anonymous)", j, c))
            i += 1
            continue
        fn = _parse_function(src, toks, i) or _parse_arrow(src, toks, i)
        if fn is None and t.kind == KIND_ID:
            fn = _parse_method(src, toks, i, owner(i))
        if fn is not None:
            out.setdefault(fn.key, fn)
            i = _index_at(toks, fn.end, i)
            continue
        i += 1
    return out


def _index_at(toks: Sequence[Token], offset: int, lo: int) -> int:
    """Index of the first token at or past ``offset`` (searching from ``lo``)."""
    j = lo
    while j < len(toks) and toks[j].start < offset:
        j += 1
    return j


def _export_flags(toks: Sequence[Token], idx: int) -> tuple[bool, bool]:
    """``(exported, default)`` for a unit whose first token is at ``idx``."""
    p1, p2 = _at(toks, idx - 1), _at(toks, idx - 2)
    if _is(p1, "export", KIND_ID):
        return True, False
    if _is(p1, "default", KIND_ID) and _is(p2, "export", KIND_ID):
        return True, True
    return False, False


def _parse_function(src: str, toks: Sequence[Token], i: int) -> JsFunc | None:
    """``[async] function [*] [name] (params) {``."""
    t = toks[i]
    start_idx = i
    async_ = False
    if t.kind == KIND_ID and t.text == "async" and _is(_at(toks, i + 1), "function", KIND_ID):
        async_ = True
        i += 1
        t = toks[i]
    if not (t.kind == KIND_ID and t.text == "function"):
        return None
    j = i + 1
    generator = False
    if _is(_at(toks, j), "*", KIND_OP):
        generator = True
        j += 1
    name = ""
    n = _at(toks, j)
    if n is not None and n.kind == KIND_ID:
        name = n.text
        j += 1
    if not _is(_at(toks, j), "(", KIND_PUNCT):
        return None
    k = _match(toks, j)
    if k < 0 or not _is(_at(toks, k + 1), "{", KIND_PUNCT):
        return None
    close = _match(toks, k + 1)
    if close < 0:
        return None
    exported, default = _export_flags(toks, start_idx)
    decl_start = toks[start_idx].start
    if not name:
        target = _assign_name(toks, start_idx)
        if target is None:
            return None  # an anonymous function expression with no nameable target
        name, ti = target
        decl_start = toks[ti].start
    return JsFunc(
        key=name,
        name=name,
        kind=KIND_FUNCTION,
        start=decl_start,
        end=toks[close].end,
        body_open=toks[k + 1].start,
        body_close=toks[close].start,
        params=_param_names(src, toks[j + 1 : k]),
        params_text=src[toks[j].end : toks[k].start],
        exported=exported,
        default_export=default,
        async_=async_,
        generator=generator,
    )


def _parse_arrow(src: str, toks: Sequence[Token], i: int) -> JsFunc | None:
    """``name = [async] (params) => {`` / ``name = [async] x => {`` / ``name: … => {``."""
    t = toks[i]
    start_idx = i
    async_ = False
    if t.kind == KIND_ID and t.text == "async":
        i += 1
        t = _at(toks, i) or t
        async_ = True
    if _is(t, "(", KIND_PUNCT):
        k = _match(toks, i)
        if k < 0 or not _is(_at(toks, k + 1), "=>", KIND_OP):
            return None
        params = _param_names(src, toks[i + 1 : k])
        params_text = src[toks[i].end : toks[k].start]
        arrow = k + 1
    elif t.kind == KIND_ID and _is(_at(toks, i + 1), "=>", KIND_OP):
        params = (t.text,)
        params_text = t.text
        arrow = i + 1
    else:
        return None
    if not _is(_at(toks, arrow + 1), "{", KIND_PUNCT):
        return None  # expression-bodied arrow: no body to replace
    close = _match(toks, arrow + 1)
    if close < 0:
        return None
    target = _assign_name(toks, start_idx)
    if target is None:
        return None
    name, ti = target
    exported, default = _export_flags(toks, ti)
    return JsFunc(
        key=name,
        name=name,
        kind=KIND_ARROW,
        start=toks[ti].start,
        end=toks[close].end,
        body_open=toks[arrow + 1].start,
        body_close=toks[close].start,
        params=params,
        params_text=params_text,
        exported=exported,
        default_export=default,
        async_=async_,
    )


def _parse_method(src: str, toks: Sequence[Token], i: int, owner: str) -> JsFunc | None:
    """``[async|static|get|set] [*] name (params) {`` inside a class or object literal."""
    t = toks[i]
    if t.kind != KIND_ID or t.text in _NOT_METHOD_NAMES or t.text in _METHOD_MODIFIERS:
        return None
    prev = _at(toks, i - 1)
    ok_prev = (
        prev is None
        or (prev.kind == KIND_PUNCT and prev.text in _METHOD_PREV)
        or (prev.kind == KIND_ID and prev.text in _METHOD_MODIFIERS)
        or _is(prev, "*", KIND_OP)
    )
    if not ok_prev or not _is(_at(toks, i + 1), "(", KIND_PUNCT):
        return None
    k = _match(toks, i + 1)
    if k < 0 or not _is(_at(toks, k + 1), "{", KIND_PUNCT):
        return None
    close = _match(toks, k + 1)
    if close < 0:
        return None
    async_ = prev is not None and prev.kind == KIND_ID and prev.text == "async"
    name = t.text
    key = f"{owner}.{name}" if owner else name
    return JsFunc(
        key=key,
        name=name,
        kind=KIND_METHOD,
        start=t.start,
        end=toks[close].end,
        body_open=toks[k + 1].start,
        body_close=toks[close].start,
        params=_param_names(src, toks[i + 2 : k]),
        params_text=src[toks[i + 1].end : toks[k].start],
        async_=async_,
    )


# ---------------------------------------------------------------------------
# module system + export wiring
# ---------------------------------------------------------------------------


def is_esm(src: str) -> bool:
    """``export``/``import`` statements at line start → ES module."""
    return re.search(r"^\s*(export\s|import\s)", src, re.M) is not None


def has_cjs_exports(src: str) -> bool:
    """``module.exports`` / ``exports.x`` present → CommonJS export wiring exists."""
    return re.search(r"\bmodule\.exports\b|(^|[^.\w])exports\.", src) is not None


def _decl_text(fn: JsFunc, body: str, *, esm: bool) -> str:
    """A standalone declaration for an added unit with ``body`` (``{ … }``)."""
    head = ""
    if esm and fn.exported:
        head = "export default " if fn.default_export else "export "
    kw = ("async " if fn.async_ else "") + "function" + ("*" if fn.generator else "")
    return f"{head}{kw} {fn.name}({fn.params_text.strip()}) {body}"


def _cjs_wiring(parent_src: str, names: Sequence[str]) -> str:
    """How to export appended units in a CommonJS file: extend an existing
    ``module.exports`` object, or create one for a new file."""
    if not names:
        return ""
    if has_cjs_exports(parent_src):
        return "".join(f"module.exports.{n} = {n};\n" for n in names)
    return "module.exports = { " + ", ".join(names) + " };\n"


def _append_units(parent_src: str, gold_src: str, decls: Sequence[tuple[JsFunc, str]]) -> str:
    """Append ``decls`` (unit, body) to the parent with export wiring matched to the
    gold's module system; a new (empty) parent gets a fresh file."""
    esm = is_esm(gold_src)
    out = parent_src
    if not out.strip():
        out = "" if esm else '"use strict";\n'
    text = "\n\n".join(_decl_text(fn, body, esm=esm) for fn, body in decls)
    out = (out.rstrip("\n") + "\n\n" if out.strip() else "") + text + "\n"
    if not esm:
        exported = [fn.name for fn, _ in decls if _gold_exports(gold_src, fn.name)]
        wiring = _cjs_wiring(parent_src, exported)
        if wiring:
            out += "\n" + wiring
    return out


def _gold_exports(gold_src: str, name: str) -> bool:
    """Whether the gold module exports ``name`` (CJS forms)."""
    pat = (
        rf"module\.exports\s*=\s*\{{[^}}]*\b{re.escape(name)}\b"
        rf"|module\.exports\.{re.escape(name)}\s*="
        rf"|(^|[^.\w])exports\.{re.escape(name)}\s*="
    )
    return re.search(pat, gold_src, re.S) is not None


# ---------------------------------------------------------------------------
# stub
# ---------------------------------------------------------------------------

STUB_BODY = "{\n  return undefined;\n}"


def _replace_bodies(src: str, funcs: Iterable[JsFunc], body: str) -> str:
    """Each unit's body → ``body``, spliced last-first so earlier offsets stay valid."""
    out = src
    for fn in sorted(funcs, key=lambda f: f.body_open, reverse=True):
        out = out[: fn.body_open] + body + out[fn.body_close + 1 :]
    return out


def stub_changed_functions(parent_src: str, gold_src: str) -> str | None:
    """Every parent unit whose segment differs from the gold keeps its signature with
    a ``return undefined;`` body; top-level units the gold ADDS are appended (methods
    cannot be appended and are skipped). ``None`` = nothing to stub."""
    try:
        parent = js_functions(parent_src) if parent_src.strip() else {}
        gold = js_functions(gold_src) if gold_src.strip() else {}
    except ScanError as exc:
        raise NotConstructible(f"source not scannable: {exc}") from exc
    changed = [
        fn
        for key, fn in parent.items()
        if key not in gold or gold[key].segment(gold_src) != fn.segment(parent_src)
    ]
    added = [fn for key, fn in gold.items() if key not in parent and fn.kind != KIND_METHOD]
    if not changed and not added:
        return None
    out = _replace_bodies(parent_src, changed, STUB_BODY)
    if added:
        out = _append_units(
            out, gold_src, [(fn, STUB_BODY) for fn in sorted(added, key=lambda f: f.start)]
        )
    return out


# ---------------------------------------------------------------------------
# regression: the adjacent module
# ---------------------------------------------------------------------------

_SPECIFIER_RE = re.compile(
    r"""(?:\brequire\s*\(\s*|\bimport\s*\(\s*|\bfrom\s+|^\s*import\s+)(['"])(\.\.?/[^'"]*)\1""",
    re.M,
)


def strip_ext(path: str) -> str:
    """``a/b.test.js`` → ``a/b.test`` (longest known suffix first, so ``.d.ts`` is safe)."""
    for suf in sorted((*JS_SUFFIXES, ".json"), key=len, reverse=True):
        if path.endswith(suf):
            return path[: -len(suf)]
    return path


def module_keys(path: str) -> frozenset[str]:
    """Every specifier-resolved form a module path may be imported as."""
    bare = strip_ext(path)
    keys = {path, bare}
    if bare.endswith("/index"):
        keys.add(bare[: -len("/index")])
    return frozenset(keys)


def js_imports(text: str, importer: str) -> frozenset[str]:
    """Relative specifiers in ``text`` (``require("./x")``, ``import … from "../y.js"``,
    ``import("./z")``) resolved against the importing file's directory, normalised
    with and without their extension."""
    base = posixpath.dirname(importer)
    out: set[str] = set()
    for m in _SPECIFIER_RE.finditer(text):
        resolved = posixpath.normpath(posixpath.join(base, m.group(2)))
        if resolved.startswith("../"):
            continue
        out.add(resolved)
        out.add(strip_ext(resolved))
    return frozenset(out)


def select_poison_target(
    candidates: Sequence[str],
    *,
    target_tests: Mapping[str, str],
    src_files: Mapping[str, str],
    belt_tests: Mapping[str, str],
) -> str | None:
    """The first (sorted) candidate a belt test imports that neither a target test
    nor a module under test imports. Mappings are ``{path: text}``."""
    imported_by_target = frozenset().union(*(js_imports(t, p) for p, t in target_tests.items()))
    imported_by_src = frozenset().union(*(js_imports(t, p) for p, t in src_files.items()))
    imported_by_belt = frozenset().union(*(js_imports(t, p) for p, t in belt_tests.items()))
    for cand in sorted(candidates):
        keys = module_keys(cand)
        if keys & imported_by_target or keys & imported_by_src:
            continue
        if keys & imported_by_belt:
            return cand
    return None


def belt_test_files(
    files: Sequence[str], *, belt_scope: Sequence[str], is_test: Any, target_tests: Collection[str]
) -> list[str]:
    """Test files the regression belt re-runs, minus the target tests: ``()`` (BARE)
    = every test file; ``dir/`` entries = prefix; other entries = exact files."""
    tests = [f for f in files if is_test(f)]
    if not belt_scope:
        chosen = tests
    else:
        chosen = []
        for f in tests:
            for s in belt_scope:
                if (s.endswith("/") and f.startswith(s)) or f == s:
                    chosen.append(f)
                    break
    return [f for f in chosen if f not in set(target_tests)]


def poison_module(text: str) -> str:
    """REGRESSION: a top-level throw prepended — any test that loads the module fails."""
    return f'throw new Error("{REGRESSION_POISON_MARK}");\n' + text


# ---------------------------------------------------------------------------
# hardcode cheat
# ---------------------------------------------------------------------------

#: ``(function name, literal arg texts, expected literal text)`` — one pinned input/output.
Fact = tuple[str, tuple[str, ...], str]


def _scalar_at(src: str, toks: Sequence[Token], i: int) -> tuple[str, int] | None:
    """A number, string, ``true``/``false``/``null``/``undefined`` or negative number at
    ``i`` → ``(text, next)``."""
    t = _at(toks, i)
    if t is None:
        return None
    if t.kind in (KIND_NUM, KIND_STR):
        return src[t.start : t.end], i + 1
    if t.kind == KIND_ID and t.text in _LITERAL_WORDS:
        return t.text, i + 1
    if _is(t, "-", KIND_OP):
        n = _at(toks, i + 1)
        if n is not None and n.kind == KIND_NUM:
            return "-" + src[n.start : n.end], i + 2
    return None


def _literal_at(src: str, toks: Sequence[Token], i: int) -> tuple[str, int] | None:
    """A scalar literal, or an array/object literal built only of literals (object
    keys may be identifiers/strings)."""
    scalar = _scalar_at(src, toks, i)
    if scalar is not None:
        return scalar
    t = _at(toks, i)
    if t is None or t.kind != KIND_PUNCT or t.text not in "[{":
        return None
    k = _match(toks, i)
    if k < 0:
        return None
    j = i + 1
    while j < k:
        s = toks[j]
        if s.kind == KIND_PUNCT and s.text in ",:":
            j += 1
            continue
        if t.text == "{" and s.kind in (KIND_ID, KIND_STR) and _is(_at(toks, j + 1), ":", KIND_OP):
            j += 2
            continue
        if _is(s, ":", KIND_OP):
            j += 1
            continue
        inner = _literal_at(src, toks, j)
        if inner is None:
            return None
        j = inner[1]
    return src[t.start : toks[k].end], k + 1


def _call_at(src: str, toks: Sequence[Token], i: int) -> tuple[str, tuple[str, ...], int] | None:
    """``[obj.]name(<scalars>)`` → ``(name, arg texts, next)``."""
    j = i
    name = ""
    while True:
        t = _at(toks, j)
        if t is None or t.kind != KIND_ID:
            return None
        name = t.text
        j += 1
        if _is(_at(toks, j), ".", KIND_PUNCT):
            j += 1
            continue
        break
    if not _is(_at(toks, j), "(", KIND_PUNCT):
        return None
    k = _match(toks, j)
    if k < 0:
        return None
    args: list[str] = []
    for elem in _split_commas(toks[j + 1 : k]):
        lit = _scalar_at(src, elem, 0)
        if lit is None or lit[1] != len(elem):
            return None
        args.append(lit[0])
    return name, tuple(args), k + 1


def extract_literal_asserts(test_src: str) -> list[Fact]:
    """``(name, scalar args, expected literal)`` for every literal call/expectation the
    target test states in one of the recognised shapes; everything else is skipped."""
    try:
        toks = sig_tokens(test_src)
    except ScanError:
        return []
    out: list[Fact] = []
    seen: set[Fact] = set()

    def add(f: Fact) -> None:
        if f not in seen:
            seen.add(f)
            out.append(f)

    i = 0
    while i < len(toks):
        t = toks[i]
        # expect(f(x)).toBe(y)
        if t.kind == KIND_ID and t.text == "expect" and _is(_at(toks, i + 1), "(", KIND_PUNCT):
            k = _match(toks, i + 1)
            call = _call_at(test_src, toks, i + 2) if k > 0 else None
            if (
                call is not None
                and call[2] == k
                and _is(_at(toks, k + 1), ".", KIND_PUNCT)
                and _at(toks, k + 2) is not None
                and toks[k + 2].text in _EXPECT_VERBS
                and _is(_at(toks, k + 3), "(", KIND_PUNCT)
            ):
                lit = _literal_at(test_src, toks, k + 4)
                if lit is not None and _is(_at(toks, lit[1]), ")", KIND_PUNCT):
                    add((call[0], call[1], lit[0]))
        # assert.equal(f(x), y) / t.is(f(x), y)
        elif (
            t.kind == KIND_ID
            and _is(_at(toks, i + 1), ".", KIND_PUNCT)
            and _at(toks, i + 2) is not None
            and toks[i + 2].kind == KIND_ID
            and _is(_at(toks, i + 3), "(", KIND_PUNCT)
            and (
                (t.text == "assert" and toks[i + 2].text in _ASSERT_VERBS)
                or (t.text == "t" and toks[i + 2].text in _T_VERBS)
            )
        ):
            k = _match(toks, i + 3)
            if k > 0:
                elems = _split_commas(toks[i + 4 : k])
                if len(elems) >= 2:
                    for got, want in ((elems[0], elems[1]), (elems[1], elems[0])):
                        call = _call_at(test_src, got, 0)
                        lit = _literal_at(test_src, want, 0)
                        if (
                            call is not None
                            and call[2] == len(got)
                            and lit is not None
                            and lit[1] == len(want)
                        ):
                            add((call[0], call[1], lit[0]))
                            break
        i += 1
    return out


def _guard(fn: JsFunc, args: Sequence[str], expected: str) -> str | None:
    if len(args) > len(fn.params):
        return None
    names = fn.params[: len(args)]
    if any(not n for n in names):
        return None
    cond = " && ".join(f"{n} === {a}" for n, a in zip(names, args, strict=True)) or "true"
    return f"  if ({cond}) {{\n    return {expected};\n  }}\n"


def build_hardcode_cheat(parent_src: str, gold_src: str, facts: Sequence[Fact]) -> str | None:
    """The parent with each fact special-cased and NOTHING implemented; units the
    parent lacks are appended with the GOLD signature and only the guards.
    ``None`` = not constructible."""
    if not facts:
        return None
    try:
        funcs = js_functions(parent_src) if parent_src.strip() else {}
        gold = js_functions(gold_src) if gold_src.strip() else {}
    except ScanError as exc:
        raise NotConstructible(f"source not scannable: {exc}") from exc
    by_name: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    for name, args, expected in facts:
        by_name.setdefault(name, []).append((args, expected))
    inserts: list[tuple[JsFunc, str]] = []
    appended: list[tuple[JsFunc, str]] = []
    for name, pairs in by_name.items():
        here = sorted((f for f in funcs.values() if f.name == name), key=lambda f: f.start)
        if here:
            fn = here[0]
            guards = "".join(g for g in (_guard(fn, a, e) for a, e in pairs) if g)
            if guards:
                inserts.append((fn, guards))
            continue
        there = sorted(
            (f for f in gold.values() if f.name == name and f.kind != KIND_METHOD),
            key=lambda f: f.start,
        )
        if not there:
            continue
        fn = there[0]
        guards = "".join(g for g in (_guard(fn, a, e) for a, e in pairs) if g)
        if guards:
            appended.append((fn, "{\n" + guards + "  return undefined;\n}"))
    if not inserts and not appended:
        return None
    out = parent_src
    for fn, guards in sorted(inserts, key=lambda t: t[0].body_open, reverse=True):
        at = fn.body_open + 1
        out = out[:at] + "\n" + guards.rstrip("\n") + out[at:]
    if appended:
        out = _append_units(out, gold_src, appended)
    return out


# ---------------------------------------------------------------------------
# env poison
# ---------------------------------------------------------------------------


def gold_copy_path(target: str) -> str:
    """``src/calc.js`` → ``src/calc.negctrl_env_poison_gold.js`` (beside the target so
    the gold's own relative imports keep resolving)."""
    bare = strip_ext(target)
    return f"{bare}{ENV_POISON_GOLD_SUFFIX}{target[len(bare) :]}"


def env_poison_setup_cjs(target: str, gold_copy: str) -> str:
    """The jest/mocha hook: load the gold copy and patch the real module's exports
    object in place (a fresh ``require`` in the test sees the gold functions)."""
    return (
        f"// {ENV_POISON_MARK}: state pollution, not implementation\n"
        f'process.env.NEGCTRL_ENV_POISON = "1";\n'
        f'const path = require("node:path");\n'
        f"const target = path.resolve(__dirname, {json.dumps(target)});\n"
        f"const gold = path.resolve(__dirname, {json.dumps(gold_copy)});\n"
        f"const real = require(target);\n"
        f"const fake = require(gold);\n"
        f'if (real && (typeof real === "object" || typeof real === "function")) {{\n'
        f"  Object.assign(real, fake);\n"
        f"}}\n"
        f"try {{\n"
        f"  require.cache[target] = {{ id: target, filename: target, loaded: true, exports: fake }};\n"
        f"}} catch (_e) {{\n"
        f"  // a sandboxed require.cache (jest) is read-only: the in-place patch above stands\n"
        f"}}\n"
    )


def env_poison_setup_esm(target: str, gold_copy: str) -> str:
    """The vitest hook: mock the module id with the gold copy."""
    return (
        f"// {ENV_POISON_MARK}: state pollution, not implementation\n"
        f'import {{ vi }} from "vitest";\n'
        f'process.env.NEGCTRL_ENV_POISON = "1";\n'
        f"vi.mock({json.dumps('./' + target)}, () => import({json.dumps('./' + gold_copy)}));\n"
    )


def _merge_json_list(doc: dict[str, Any], *keys: str, value: str) -> None:
    """Append ``value`` to the list at ``doc[keys…]`` in place (a scalar becomes a list;
    missing objects are created; a value already present is not duplicated)."""
    node = doc
    for k in keys[:-1]:
        nxt = node.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            node[k] = nxt
        node = nxt
    cur = node.get(keys[-1])
    lst = list(cur) if isinstance(cur, list) else ([cur] if isinstance(cur, str) else [])
    if value not in lst:
        lst.append(value)
    node[keys[-1]] = lst


#: Root-level files the env-poison planner may read or merge (the runner reads
#: exactly these and passes their text; anything else at the root is invisible).
ENV_POISON_CONFIG_FILES: tuple[str, ...] = (
    "package.json",
    "jest.config.js",
    "jest.config.cjs",
    "jest.config.mjs",
    "jest.config.ts",
    "jest.config.json",
    "vitest.config.js",
    "vitest.config.cjs",
    "vitest.config.mjs",
    "vitest.config.ts",
    "vitest.config.mts",
    "vitest.config.cts",
    "vite.config.js",
    "vite.config.cjs",
    "vite.config.mjs",
    "vite.config.ts",
    "vite.config.mts",
    "vite.config.cts",
    ".mocharc",
    ".mocharc.js",
    ".mocharc.cjs",
    ".mocharc.mjs",
    ".mocharc.yml",
    ".mocharc.yaml",
    ".mocharc.jsonc",
    ".mocharc.json",
)


def env_poison_plan(
    tool: str,
    *,
    target: str,
    gold_src: str,
    root_files: Mapping[str, str],
) -> tuple[dict[str, str], str]:
    """Files to write ``{rel: text}`` and a note naming the vector, for ``tool`` in
    ``node | jest | vitest | mocha``. ``root_files`` holds the text of every existing
    :data:`ENV_POISON_CONFIG_FILES` entry. Raises :class:`NotConstructible` when the
    runner has no collection-time hook or an existing config cannot be merged
    textually (JSON is merged; JS/YAML configs are never rewritten by guesswork)."""
    copy = gold_copy_path(target)
    files: dict[str, str] = {copy: gold_src}
    tail = f"(patches {target} exports with the gold copy {copy})"
    if tool == "node":
        raise NotConstructible(
            "node --test has no configuration-file hook (no setupFiles / require); "
            "NODE_OPTIONS is harness-controlled — the collection-time vector does not exist"
        )
    if tool == "jest":
        files[ENV_POISON_SETUP_CJS] = env_poison_setup_cjs(target, copy)
        entry = f"<rootDir>/{ENV_POISON_SETUP_CJS}"
        pkg = _load_json(root_files.get("package.json"), "package.json")
        if isinstance(pkg.get("jest"), dict):
            _merge_json_list(pkg, "jest", "setupFiles", value=entry)
            files["package.json"] = json.dumps(pkg, indent=2) + "\n"
            return files, f"jest setupFiles merged into package.json#jest {tail}"
        if "jest.config.json" in root_files:
            cfg = _load_json(root_files["jest.config.json"], "jest.config.json")
            _merge_json_list(cfg, "setupFiles", value=entry)
            files["jest.config.json"] = json.dumps(cfg, indent=2) + "\n"
            return files, f"jest setupFiles merged into jest.config.json {tail}"
        existing = sorted(n for n in root_files if _JEST_CONFIG_RE.match(n))
        if existing:
            raise NotConstructible(f"existing jest config {existing[0]} cannot be merged textually")
        files["jest.config.cjs"] = f"module.exports = {{ setupFiles: [{json.dumps(entry)}] }};\n"
        return files, f"jest setupFiles via new jest.config.cjs {tail}"
    if tool == "mocha":
        files[ENV_POISON_SETUP_CJS] = env_poison_setup_cjs(target, copy)
        entry = f"./{ENV_POISON_SETUP_CJS}"
        pkg = _load_json(root_files.get("package.json"), "package.json")
        if isinstance(pkg.get("mocha"), dict):
            _merge_json_list(pkg, "mocha", "require", value=entry)
            files["package.json"] = json.dumps(pkg, indent=2) + "\n"
            return files, f"mocha require merged into package.json#mocha {tail}"
        if ".mocharc.json" in root_files:
            rc = _load_json(root_files[".mocharc.json"], ".mocharc.json")
            _merge_json_list(rc, "require", value=entry)
            files[".mocharc.json"] = json.dumps(rc, indent=2) + "\n"
            return files, f"mocha require merged into .mocharc.json {tail}"
        existing = sorted(n for n in root_files if _MOCHARC_RE.match(n))
        if existing:
            raise NotConstructible(
                f"existing mocha config {existing[0]} cannot be merged textually"
            )
        files[".mocharc.json"] = json.dumps({"require": [entry]}, indent=2) + "\n"
        return files, f"mocha require via new .mocharc.json {tail}"
    if tool == "vitest":
        existing = sorted(n for n in root_files if _VITEST_CONFIG_RE.match(n))
        if existing:
            raise NotConstructible(
                f"existing vitest/vite config {existing[0]} cannot be merged textually"
            )
        files[ENV_POISON_SETUP_ESM] = env_poison_setup_esm(target, copy)
        setup = json.dumps("./" + ENV_POISON_SETUP_ESM)
        files["vitest.config.mjs"] = f"export default {{ test: {{ setupFiles: [{setup}] }} }};\n"
        return files, (
            f"vitest setupFiles via new vitest.config.mjs + vi.mock of {target} "
            f"with the gold copy {copy}"
        )
    raise NotConstructible(f"no env_poison vector for runner {tool!r}")


def _load_json(text: str | None, name: str) -> dict[str, Any]:
    """Parse a config file's JSON; an unparseable one is ``NotConstructible`` (never guessed)."""
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise NotConstructible(f"{name} is not valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def describe() -> dict[str, Any]:
    """What this transform family is (for an apparatus stamp)."""
    return {
        "language": LANG_JAVASCRIPT,
        "family": "text",
        "stub": "return undefined bodies; added units appended with gold export wiring",
        "regression": "top-level throw in an adjacent belt-scope module",
        "hardcode_cheat": "literal guards from expect/assert/t assertions",
        "env_poison": "runner hook (jest setupFiles / mocha require / vitest setupFiles+vi.mock)",
    }
