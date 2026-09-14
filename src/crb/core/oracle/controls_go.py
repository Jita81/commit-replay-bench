"""Negative-control transforms for Go — pure text, deterministic, standard library only.

The Python controls reason over an AST. Go has no parser in the standard library and
``crb.core`` takes no dependency (ADR-0008), so — exactly as the text-level mutators do
(ADR-0009) — this module works over the tokens of :func:`crb.core.oracle.mutators_text.
tokenize` with the Go profile: strings, runes, raw strings and comments are opaque, so
no transform ever looks inside a literal, and bracket matching over the remaining
tokens is exact. The four transforms it provides, and what each honestly is:

* **stub** — every function the gold commit changed keeps its signature; its body
  becomes zero-value returns (``return 0, nil`` / ``return *new(T)``; an empty body
  when there are no results). Functions the commit ADDS are appended as such stubs
  so the target test compiles and fails on an *assertion*, never on ``undefined:``.
  ``panic("stub")`` is deliberately NOT used: a panic is also "red", but for the
  wrong reason. Imports the hollowed bodies no longer use are blank-aliased
  (``_ "fmt"``) so the file still compiles. The caller must compile-check the result
  (``go test -run '^$'``): a stub the toolchain rejects is ``not_constructible``.
* **regression** — the gold overlaid PLUS an ``init()`` panic in a NEW non-test file of
  an *adjacent package*: one inside the belt scope, outside the target package(s),
  with its own ``_test.go`` files, and not import-reachable from the target package.
  Go's target scope is the whole package (``go test ./pkg``), so a broken *function*
  in the same package is seen by belt 2, not belt 3; the adjacent **package** is the
  unit belt 3 alone can see. Under ``TARGET_ONLY`` / ``AFFECTED_DIRS`` the belt *is*
  the target package(s), so the control can never be built — the reason says so.
* **hardcode_cheat** — literal ``(call, expectation)`` pairs parsed from the target
  test (``if got := f(1, 2); got != 3 {``, ``if f(1) != 2 {``, testify
  ``assert.Equal(t, 3, f(1, 2))`` / ``EqualValues`` / ``Exactly`` / ``True`` /
  ``False``) become ``if a == 1 && b == 2 { return 3 }`` guards prepended to the
  parent function's body — nothing implemented. A function the commit adds is
  appended with the GOLD signature and only the lookup guards. Table-driven tests
  (``{1, 2, 3}`` rows) are deliberately unparsed: narrowness is the point.
* **env_poison** — Go has no collection-time hook (no ``conftest.py``, no
  ``setupFiles``); the one honest vector is an ``init()`` in a NEW non-test file of
  the same package that re-assigns a **package-level variable** the commit changed
  (``var Scale = func(a int) int { … }``) to its gold value. The graded source file
  stays byte-identical to the parent; the green, if it comes, is state pollution.
  A commit that changes only plain ``func`` declarations has no such variable, and
  the control is honestly ``not_constructible`` — there is no init-time way to
  replace a Go function.

Every function here is pure over source text (no I/O, no toolchain); the runner in
:mod:`crb.core.oracle.controls` is the I/O shell that writes files and runs the
compile check. A transform that cannot be built raises :class:`NotConstructible`
with the reason that becomes the row's note.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from crb.core.oracle.mutators_text import (
    KIND_COMMENT,
    KIND_ID,
    KIND_NUM,
    KIND_OP,
    KIND_PUNCT,
    KIND_STR,
    LANG_GO,
    PROFILES,
    ScanError,
    Token,
    tokenize,
)

GO_PROFILE = PROFILES[LANG_GO]

REGRESSION_POISON_FILE = "negctrl_regression_poison.go"
ENV_POISON_FILE = "negctrl_env_poison.go"
REGRESSION_POISON_MARK = "negctrl-regression-poison"
ENV_POISON_MARK = "negctrl-env-poison"

KIND_FUNC = "func"
KIND_METHOD = "method"
KIND_VAR = "var"  # ``var Name = func(…) … { … }`` — a function-typed package variable

_TYPE_KEYWORDS = frozenset({"func", "chan", "map", "struct", "interface"})
_NUMERIC_TYPES = frozenset(
    {
        "int",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "uintptr",
        "float32",
        "float64",
        "complex64",
        "complex128",
        "byte",
        "rune",
    }
)
_NIL_PREFIXES = ("*", "[]", "map[", "chan ", "chan<-", "<-chan", "func(", "func ")
_NIL_TYPES = frozenset({"error", "any", "interface{}", "interface {}"})
_LITERAL_WORDS = frozenset({"true", "false", "nil"})
_TESTIFY_EQUAL = frozenset({"Equal", "EqualValues", "Exactly"})
_TESTIFY_BOOL: Mapping[str, str] = {"True": "true", "False": "false"}


class NotConstructible(ValueError):
    """The cheat cannot honestly be built for this task; ``str(exc)`` is the reason."""


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------


def sig_tokens(src: str) -> list[Token]:
    """Significant tokens (comments dropped). Raises :class:`ScanError` when the
    source is not scannable — the transform is then not constructible."""
    return [t for t in tokenize(src, GO_PROFILE) if t.kind != KIND_COMMENT]


def _is(tok: Token | None, text: str, kind: str | None = None) -> bool:
    return tok is not None and tok.text == text and (kind is None or tok.kind == kind)


def _at(toks: Sequence[Token], i: int) -> Token | None:
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
    """Split a bracket-free-at-depth-0 token run on top-level commas (empty run → [])."""
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


def _text(src: str, toks: Sequence[Token]) -> str:
    return src[toks[0].start : toks[-1].end] if toks else ""


# ---------------------------------------------------------------------------
# declarations: functions, methods, function-typed variables, imports, vars
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoParam:
    name: str  # "" when unnamed (``func f(int, string)``)
    type: str


@dataclass(frozen=True)
class GoFunc:
    """One function-shaped declaration and its exact spans in the source."""

    key: str  # ``Name`` | ``Recv.Name`` | var name
    name: str
    kind: str  # KIND_FUNC | KIND_METHOD | KIND_VAR
    start: int  # offset of the declaration's first token (``func`` / ``var``)
    end: int  # offset just past the closing ``}``
    body_open: int  # offset of the body ``{``
    body_close: int  # offset of the body ``}``
    params: tuple[GoParam, ...]
    results: tuple[str, ...]  # result TYPE texts (named results resolved to types)
    signature: str  # ``func Name(a, b int) int``; for a var, the literal's ``func(a int) int``

    def segment(self, src: str) -> str:
        return src[self.start : self.end]

    def stub_body(self) -> str:
        """``{ return <zeros> }`` (tab-indented, gofmt-shaped), or ``{}`` for no results."""
        if not self.results:
            return "{}"
        zeros = ", ".join(zero_value(r) for r in self.results)
        return "{\n\treturn " + zeros + "\n}"


def zero_value(type_text: str) -> str:
    """The Go zero value for a result type, as source text.

    Well-known kinds get their literal (``0``, ``""``, ``false``, ``nil``); anything
    else (named types, structs, arrays, type parameters) uses ``*new(T)``, which is the
    zero value of ANY type ``T`` by the language definition — so the stub compiles
    without the transform ever reasoning about what ``T`` is.
    """
    t = " ".join(type_text.split())
    if t in _NUMERIC_TYPES:
        return "0"
    if t == "string":
        return '""'
    if t == "bool":
        return "false"
    if t in _NIL_TYPES or t.startswith(_NIL_PREFIXES):
        return "nil"
    return f"*new({t})"


def _param_list(src: str, toks: Sequence[Token]) -> tuple[GoParam, ...]:
    """Parse the tokens INSIDE a parameter/result parenthesis into ``(name, type)`` pairs
    honouring Go's rule that a list is either all-named or all-unnamed, with grouped
    names (``a, b int``) taking the type of the next typed element."""
    elems = _split_commas(toks)
    if not elems:
        return ()

    def named(e: Sequence[Token]) -> bool:
        return (
            len(e) >= 2
            and e[0].kind == KIND_ID
            and e[0].text not in _TYPE_KEYWORDS
            and not (e[1].kind == KIND_PUNCT and e[1].text == ".")
        )

    if not any(named(e) for e in elems):
        return tuple(GoParam("", _text(src, e)) for e in elems)
    out: list[GoParam] = []
    pending: list[str] = []
    for e in elems:
        if len(e) == 1 and e[0].kind == KIND_ID:
            pending.append(e[0].text)
            continue
        type_text = _text(src, e[1:])
        for n in pending:
            out.append(GoParam(n, type_text))
        pending = []
        out.append(GoParam(e[0].text, type_text))
    for n in pending:  # trailing names without a type: malformed, keep them unnamed
        out.append(GoParam(n, ""))
    return tuple(out)


def _results(src: str, toks: Sequence[Token], j: int) -> tuple[tuple[str, ...], int]:
    """Result types starting at token ``j`` (just after the parameter ``)``) up to the
    body ``{``; returns ``(types, index_of_body_brace)`` or ``((), -1)``."""
    t = _at(toks, j)
    if t is None:
        return (), -1
    if _is(t, "{", KIND_PUNCT):
        return (), j
    if _is(t, "(", KIND_PUNCT):
        k = _match(toks, j)
        if k < 0:
            return (), -1
        types = tuple(p.type for p in _param_list(src, toks[j + 1 : k]))
        return types, (k + 1 if _is(_at(toks, k + 1), "{", KIND_PUNCT) else -1)
    # a single (possibly composite) type: scan to the body brace, skipping the braces
    # of ``struct{…}`` / ``interface{…}`` literals in the type
    k = j
    while k < len(toks):
        tk = toks[k]
        if tk.kind == KIND_PUNCT and tk.text in "([":
            k = _match(toks, k)
            if k < 0:
                return (), -1
            k += 1
            continue
        if tk.kind == KIND_PUNCT and tk.text == "{":
            prev = toks[k - 1]
            if prev.kind == KIND_ID and prev.text in ("struct", "interface"):
                k = _match(toks, k)
                if k < 0:
                    return (), -1
                k += 1
                continue
            return (src[toks[j].start : toks[k - 1].end].strip(),), k
        k += 1
    return (), -1


def _receiver_base(toks: Sequence[Token]) -> str:
    """``(c *Command)`` / ``(*Command)`` / ``(c Command[T])`` → ``Command``."""
    ids = [t for t in toks if t.kind == KIND_ID]
    if not ids:
        return ""
    # the type name is the last identifier before a ``[`` or the end
    for i, t in enumerate(toks):
        if t.kind == KIND_PUNCT and t.text == "[":
            before = [x for x in toks[:i] if x.kind == KIND_ID]
            return before[-1].text if before else ""
    return ids[-1].text


def _parse_func(src: str, toks: Sequence[Token], i: int, *, decl_start: int) -> GoFunc | None:
    """Parse ``func [recv] [Name] [tparams] (params) [results] {`` at token ``i``."""
    j = i + 1
    recv = ""
    kind = KIND_FUNC
    t = _at(toks, j)
    if _is(t, "(", KIND_PUNCT):
        k = _match(toks, j)
        if k < 0:
            return None
        nxt, after = _at(toks, k + 1), _at(toks, k + 2)
        # a method is ``func (recv) Name(`` / ``Name[``; ``func(a int) int {`` is a
        # LITERAL whose result type merely looks like a name — never a method.
        if (
            nxt is not None
            and nxt.kind == KIND_ID
            and after is not None
            and after.kind == KIND_PUNCT
            and after.text in "(["
        ):
            recv = _receiver_base(toks[j + 1 : k])
            kind = KIND_METHOD
            j = k + 1
    name = ""
    t = _at(toks, j)
    if t is not None and t.kind == KIND_ID and t.text != "func":
        name = t.text
        j += 1
    t = _at(toks, j)
    if _is(t, "[", KIND_PUNCT):  # type parameters
        j = _match(toks, j)
        if j < 0:
            return None
        j += 1
    t = _at(toks, j)
    if not _is(t, "(", KIND_PUNCT):
        return None
    k = _match(toks, j)
    if k < 0:
        return None
    params = _param_list(src, toks[j + 1 : k])
    results, body = _results(src, toks, k + 1)
    if body < 0:
        return None
    close = _match(toks, body)
    if close < 0:
        return None
    key = f"{recv}.{name}" if recv else name
    signature = src[toks[i].start : toks[body].start].rstrip()
    return GoFunc(
        key=key,
        name=name,
        kind=kind,
        start=decl_start,
        end=toks[close].end,
        body_open=toks[body].start,
        body_close=toks[close].start,
        params=params,
        results=results,
        signature=signature,
    )


def go_functions(src: str) -> dict[str, GoFunc]:
    """Every top-level function, method and ``var Name = func(…) … {…}`` in ``src``,
    keyed ``Name`` / ``Recv.Name``. First definition of a key wins (deterministic).
    Raises :class:`ScanError` on an unscannable source."""
    toks = sig_tokens(src)
    out: dict[str, GoFunc] = {}
    i = 0
    depth = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == KIND_PUNCT and t.text in _OPEN:
            depth += 1
        elif t.kind == KIND_PUNCT and t.text in ")]}":
            depth -= 1
        elif depth == 0 and t.kind == KIND_ID:
            prev = _at(toks, i - 1)
            if t.text == "func" and not _is(prev, "=", KIND_OP):
                fn = _parse_func(src, toks, i, decl_start=t.start)
                if fn is not None and fn.name:
                    out.setdefault(fn.key, fn)
                    i = _index_at(toks, fn.end, i)
                    continue
            elif (
                t.text == "var"
                and _at(toks, i + 1) is not None
                and toks[i + 1].kind == KIND_ID
                and _is(_at(toks, i + 2), "=", KIND_OP)
                and _is(_at(toks, i + 3), "func", KIND_ID)
            ):
                fn = _parse_func(src, toks, i + 3, decl_start=t.start)
                if fn is not None and not fn.name:
                    name = toks[i + 1].text
                    lit = GoFunc(
                        key=name,
                        name=name,
                        kind=KIND_VAR,
                        start=fn.start,
                        end=fn.end,
                        body_open=fn.body_open,
                        body_close=fn.body_close,
                        params=fn.params,
                        results=fn.results,
                        signature=fn.signature,  # ``func(a int) int``
                    )
                    out.setdefault(name, lit)
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


def package_clause(src: str) -> str:
    """``package X`` from the source (``""`` if absent)."""
    m = re.search(r"^[ \t]*package[ \t]+([A-Za-z_][A-Za-z0-9_]*)", src, re.M)
    return f"package {m.group(1)}" if m else ""


def package_name(src: str) -> str:
    pc = package_clause(src)
    return pc.split()[1] if pc else ""


@dataclass(frozen=True)
class GoImport:
    alias: str  # "" when none; "_" / "." kept verbatim
    path: str
    start: int  # span of the import SPEC (alias + path) in the source
    end: int

    @property
    def name(self) -> str:
        """The identifier code uses to reference this import."""
        if self.alias and self.alias not in ("_", "."):
            return self.alias
        last = self.path.rstrip("/").rsplit("/", 1)[-1]
        if re.fullmatch(r"v\d+", last) and "/" in self.path:
            last = self.path.rstrip("/").rsplit("/", 2)[-2]
        last = re.sub(r"\.v\d+$", "", last)
        if last.startswith("go-"):
            last = last[3:]
        return last.replace("-", "").replace(".", "")

    def spec(self) -> str:
        """``[alias ]"path"`` as it appears in an import declaration."""
        return f'{self.alias} "{self.path}"' if self.alias else f'"{self.path}"'


def go_imports(src: str) -> tuple[GoImport, ...]:
    """Every import spec (single and grouped forms) with its exact span."""
    toks = sig_tokens(src)
    out: list[GoImport] = []
    i = 0
    depth = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == KIND_PUNCT and t.text in _OPEN:
            depth += 1
        elif t.kind == KIND_PUNCT and t.text in ")]}":
            depth -= 1
        elif depth == 0 and t.kind == KIND_ID and t.text == "import":
            nxt = _at(toks, i + 1)
            if _is(nxt, "(", KIND_PUNCT):
                k = _match(toks, i + 1)
                if k < 0:
                    break
                specs = toks[i + 2 : k]
                j = 0
                while j < len(specs):
                    s = specs[j]
                    if s.kind == KIND_STR:
                        out.append(GoImport("", s.text.strip('"`'), s.start, s.end))
                        j += 1
                    elif (
                        s.kind in (KIND_ID, KIND_PUNCT)
                        and _at(specs, j + 1) is not None
                        and specs[j + 1].kind == KIND_STR
                    ):
                        p = specs[j + 1]
                        out.append(GoImport(s.text, p.text.strip('"`'), s.start, p.end))
                        j += 2
                    else:
                        j += 1
                i = k + 1
                continue
            if nxt is not None and nxt.kind == KIND_STR:
                out.append(GoImport("", nxt.text.strip('"`'), nxt.start, nxt.end))
                i += 2
                continue
            nn = _at(toks, i + 2)
            if nxt is not None and nn is not None and nn.kind == KIND_STR:
                out.append(GoImport(nxt.text, nn.text.strip('"`'), nxt.start, nn.end))
                i += 3
                continue
        i += 1
    return tuple(out)


def referenced_packages(src: str, toks: Sequence[Token] | None = None) -> frozenset[str]:
    """Identifiers used as ``name.`` qualifiers anywhere in the tokens."""
    toks = sig_tokens(src) if toks is None else toks
    used: set[str] = set()
    for i, t in enumerate(toks):
        nxt = _at(toks, i + 1)
        if t.kind == KIND_ID and _is(nxt, ".", KIND_PUNCT):
            prev = _at(toks, i - 1)
            if not _is(prev, ".", KIND_PUNCT):
                used.add(t.text)
    return frozenset(used)


def blank_unused_imports(src: str) -> str:
    """Re-alias every import whose name is no longer referenced as ``_ "path"`` — a
    hollowed body can leave ``imported and not used`` errors; a blank import keeps
    the file compiling without adding behaviour."""
    imports = go_imports(src)
    if not imports:
        return src
    toks = sig_tokens(src)
    spans = [(im.start, im.end) for im in imports]
    outside = [t for t in toks if not any(s <= t.start < e for s, e in spans)]
    used = referenced_packages(src, outside)
    out = src
    for im in sorted(imports, key=lambda x: x.start, reverse=True):
        if im.alias in ("_", ".") or im.name in used:
            continue
        out = out[: im.start] + f'_ "{im.path}"' + out[im.end :]
    return out


def add_imports(src: str, specs: Iterable[GoImport]) -> str:
    """Insert ``import [alias] "path"`` lines after the package clause (a file may
    carry any number of import declarations)."""
    lines = [f"import {im.spec()}" for im in specs]
    if not lines:
        return src
    m = re.search(r"^[ \t]*package[ \t]+[A-Za-z_][A-Za-z0-9_]*[^\n]*\n", src, re.M)
    if not m:
        return "\n".join(lines) + "\n" + src
    return src[: m.end()] + "\n" + "\n".join(lines) + "\n" + src[m.end() :]


def imports_needed(text: str, *, gold_src: str, parent_src: str) -> list[GoImport]:
    """Gold imports that ``text`` references but the parent does not import."""
    have = {im.name for im in go_imports(parent_src)} if parent_src.strip() else set()
    wanted = referenced_packages(text)
    return [im for im in go_imports(gold_src) if im.name in wanted and im.name not in have]


# ---------------------------------------------------------------------------
# stub
# ---------------------------------------------------------------------------


def _replace_bodies(src: str, funcs: Iterable[GoFunc]) -> str:
    out = src
    for fn in sorted(funcs, key=lambda f: f.body_open, reverse=True):
        out = out[: fn.body_open] + fn.stub_body() + out[fn.body_close + 1 :]
    return out


def _decl_stub(fn: GoFunc) -> str:
    if fn.kind == KIND_VAR:
        return f"var {fn.name} = {fn.signature} {fn.stub_body()}"
    return f"{fn.signature} {fn.stub_body()}"


def stub_changed_functions(parent_src: str, gold_src: str) -> str | None:
    """Hollow out the commit's change: every parent function/method/func-var whose
    segment differs from the gold keeps its signature with a zero-value body;
    functions the gold ADDS are appended as stubs. ``None`` = nothing to stub.
    Raises :class:`NotConstructible` when either side is unscannable."""
    try:
        parent = go_functions(parent_src) if parent_src.strip() else {}
        gold = go_functions(gold_src) if gold_src.strip() else {}
    except ScanError as exc:
        raise NotConstructible(f"source not scannable: {exc}") from exc
    changed = [
        fn
        for key, fn in parent.items()
        if key not in gold or gold[key].segment(gold_src) != fn.segment(parent_src)
    ]
    added = [fn for key, fn in gold.items() if key not in parent]
    if not changed and not added:
        return None
    out = _replace_bodies(parent_src, changed)
    if changed:
        out = blank_unused_imports(out)
    if added:
        stubs = "\n\n".join(_decl_stub(fn) for fn in sorted(added, key=lambda f: f.start))
        if not out.strip():
            out = package_clause(gold_src) + "\n"
        out = out.rstrip("\n") + "\n\n" + stubs + "\n"
        out = add_imports(out, imports_needed(stubs, gold_src=gold_src, parent_src=parent_src))
    return out


# ---------------------------------------------------------------------------
# regression: the adjacent package
# ---------------------------------------------------------------------------


def module_path(go_mod: str) -> str:
    m = re.search(r"^[ \t]*module[ \t]+(\S+)", go_mod, re.M)
    return m.group(1).strip('"') if m else ""


def package_dir(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def scope_dirs(scope: Sequence[str], all_dirs: Iterable[str], *, module: str) -> set[str]:
    """Package directories a runner scope addresses: ``()`` (BARE) = every package;
    ``./x`` = ``x``; ``./x/...`` = ``x`` and below; ``./...`` = everything; a full
    import path is stripped of the module prefix."""
    dirs = set(all_dirs)
    if not scope:
        return dirs
    out: set[str] = set()
    for raw in scope:
        s = raw.strip()
        if module and s.startswith(module):
            s = s[len(module) :].lstrip("/")
        if s.startswith("./"):
            s = s[2:]
        if s == ".":
            s = ""
        if s == "...":
            return dirs
        if s.endswith("/..."):
            prefix = s[: -len("/...")].rstrip("/")
            out |= {d for d in dirs if d == prefix or d.startswith(prefix + "/")}
        else:
            out.add(s.rstrip("/"))
    return out & dirs


def in_module_imports(src: str, *, module: str) -> set[str]:
    """Package dirs (relative to the module root) that ``src`` imports."""
    out: set[str] = set()
    for im in go_imports(src):
        p = im.path
        if p == module:
            out.add("")
        elif p.startswith(module + "/"):
            out.add(p[len(module) + 1 :])
    return out


def reachable_dirs(start: Iterable[str], imports_by_dir: Mapping[str, set[str]]) -> set[str]:
    """Transitive closure of in-module package imports from ``start`` (inclusive)."""
    seen: set[str] = set()
    stack = list(start)
    while stack:
        d = stack.pop()
        if d in seen:
            continue
        seen.add(d)
        stack.extend(sorted(imports_by_dir.get(d, ())))
    return seen


def select_adjacent_package(
    files: Sequence[str],
    *,
    texts: Mapping[str, str],
    module: str,
    target_dirs: Iterable[str],
    belt_scope: Sequence[str],
) -> str | None:
    """The first (sorted) package directory that is inside the belt scope, is not a
    target package, has at least one ``_test.go`` AND one non-test ``.go`` file, and
    is not import-reachable from the target package(s). ``None`` = none exists.
    ``texts`` maps every ``.go`` path to its source (for the import graph)."""
    go_files = [f for f in files if f.endswith(".go")]
    dirs = {package_dir(f) for f in go_files}
    imports_by_dir: dict[str, set[str]] = {}
    for f in go_files:
        imports_by_dir.setdefault(package_dir(f), set()).update(
            in_module_imports(texts.get(f, ""), module=module)
        )
    targets = set(target_dirs)
    excluded = reachable_dirs(targets, imports_by_dir)
    in_belt = scope_dirs(belt_scope, dirs, module=module)
    for d in sorted(in_belt - excluded):
        members = [f for f in go_files if package_dir(f) == d]
        if any(f.endswith("_test.go") for f in members) and any(
            not f.endswith("_test.go") for f in members
        ):
            return d
    return None


def regression_poison_file(pkg: str) -> str:
    """A NEW non-test file whose ``init()`` panics: every test binary of the package
    fails before a single test runs — guaranteed observable by belt 3, and it
    compiles by construction."""
    return f'package {pkg}\n\nfunc init() {{ panic("{REGRESSION_POISON_MARK}") }}\n'


# ---------------------------------------------------------------------------
# hardcode cheat
# ---------------------------------------------------------------------------

Fact = tuple[str, tuple[str, ...], str]  # (func name, literal arg texts, expected literal text)


def _literal_at(src: str, toks: Sequence[Token], i: int) -> tuple[str, int] | None:
    """A literal token at ``i`` (``-`` prefix on a number allowed) → ``(text, next)``."""
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


def _call_at(src: str, toks: Sequence[Token], i: int) -> tuple[str, tuple[str, ...], int] | None:
    """``[pkg.]name(<literals>)`` at ``i`` → ``(name, arg texts, next)``; ``None`` if the
    call has a non-literal argument."""
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
        lit = _literal_at(src, elem, 0)
        if lit is None or lit[1] != len(elem):
            return None
        args.append(lit[0])
    return name, tuple(args), k + 1


def extract_literal_asserts(test_src: str) -> list[Fact]:
    """``(name, literal args, expected literal)`` for every literal call/expectation
    pair the target test pins down. Anything else (variables, table rows, multi-value
    returns) is skipped — the cheat may only special-case what the test states."""
    try:
        toks = sig_tokens(test_src)
    except ScanError:
        return []
    out: list[Fact] = []
    seen: set[Fact] = set()

    def add(fact: Fact) -> None:
        if fact not in seen:
            seen.add(fact)
            out.append(fact)

    i = 0
    while i < len(toks):
        t = toks[i]
        # if got := f(x); got != want {   |   if f(x) != want {   |   if want != f(x) {
        if t.kind == KIND_ID and t.text == "if":
            j = i + 1
            n1, n2 = _at(toks, j), _at(toks, j + 1)
            if n1 is not None and n1.kind == KIND_ID and _is(n2, ":=", KIND_OP):
                call = _call_at(test_src, toks, j + 2)
                if (
                    call is not None
                    and _is(_at(toks, call[2]), ";", KIND_PUNCT)
                    and _is(_at(toks, call[2] + 1), n1.text, KIND_ID)
                    and _is(_at(toks, call[2] + 2), "!=", KIND_OP)
                ):
                    lit = _literal_at(test_src, toks, call[2] + 3)
                    if lit is not None and _is(_at(toks, lit[1]), "{", KIND_PUNCT):
                        add((call[0], call[1], lit[0]))
            else:
                call = _call_at(test_src, toks, j)
                if call is not None and _is(_at(toks, call[2]), "!=", KIND_OP):
                    lit = _literal_at(test_src, toks, call[2] + 1)
                    if lit is not None and _is(_at(toks, lit[1]), "{", KIND_PUNCT):
                        add((call[0], call[1], lit[0]))
                else:
                    lit = _literal_at(test_src, toks, j)
                    if lit is not None and _is(_at(toks, lit[1]), "!=", KIND_OP):
                        call = _call_at(test_src, toks, lit[1] + 1)
                        if call is not None and _is(_at(toks, call[2]), "{", KIND_PUNCT):
                            add((call[0], call[1], lit[0]))
        # assert.Equal(t, want, f(x)) / assert.Equal(t, f(x), want) / assert.True(t, f(x))
        elif (
            t.kind == KIND_ID
            and _is(_at(toks, i + 1), ".", KIND_PUNCT)
            and _at(toks, i + 2) is not None
            and toks[i + 2].kind == KIND_ID
            and (toks[i + 2].text in _TESTIFY_EQUAL or toks[i + 2].text in _TESTIFY_BOOL)
            and _is(_at(toks, i + 3), "(", KIND_PUNCT)
        ):
            k = _match(toks, i + 3)
            if k > 0:
                elems = _split_commas(toks[i + 4 : k])
                verb = toks[i + 2].text
                if verb in _TESTIFY_BOOL and len(elems) >= 2:
                    call = _call_at(test_src, elems[1], 0)
                    if call is not None and call[2] == len(elems[1]):
                        add((call[0], call[1], _TESTIFY_BOOL[verb]))
                elif verb in _TESTIFY_EQUAL and len(elems) >= 3:
                    a, b = elems[1], elems[2]
                    for want, got in ((a, b), (b, a)):
                        lit = _literal_at(test_src, want, 0)
                        call = _call_at(test_src, got, 0)
                        if (
                            lit is not None
                            and lit[1] == len(want)
                            and call is not None
                            and call[2] == len(got)
                        ):
                            add((call[0], call[1], lit[0]))
                            break
        i += 1
    return out


def _guard(fn: GoFunc, args: Sequence[str], expected: str) -> str | None:
    """``if a == 1 && b == 2 {\\n\\t\\treturn 3\\n\\t}`` for one fact, or ``None`` when the
    function's shape cannot carry it (unnamed/variadic params, ≠ 1 result)."""
    if len(fn.results) != 1 or len(args) > len(fn.params):
        return None
    names = [p.name for p in fn.params[: len(args)]]
    if any(not n or n == "_" for n in names):
        return None
    if any(p.type.startswith("...") for p in fn.params[: len(args)]):
        return None
    cond = " && ".join(f"{n} == {a}" for n, a in zip(names, args, strict=True)) or "true"
    return f"\tif {cond} {{\n\t\treturn {expected}\n\t}}\n"


def build_hardcode_cheat(parent_src: str, gold_src: str, facts: Sequence[Fact]) -> str | None:
    """The parent with each fact special-cased and NOTHING implemented: existing
    functions get a literal guard prepended to their (buggy) body; functions the
    parent lacks are appended with the GOLD signature and only the guards.
    ``None`` = not constructible. Raises :class:`NotConstructible` on unscannable
    source."""
    if not facts:
        return None
    try:
        funcs = go_functions(parent_src) if parent_src.strip() else {}
        gold = go_functions(gold_src) if gold_src.strip() else {}
    except ScanError as exc:
        raise NotConstructible(f"source not scannable: {exc}") from exc
    by_name: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    for name, args, expected in facts:
        by_name.setdefault(name, []).append((args, expected))

    inserts: list[tuple[GoFunc, str]] = []
    appended: list[str] = []
    for name, pairs in by_name.items():
        here = sorted((f for f in funcs.values() if f.name == name), key=lambda f: f.start)
        if here:
            fn = here[0]
            guards = "".join(g for g in (_guard(fn, a, e) for a, e in pairs) if g)
            if guards:
                inserts.append((fn, guards))
            continue
        there = sorted((f for f in gold.values() if f.name == name), key=lambda f: f.start)
        if not there:
            continue
        fn = there[0]
        guards = "".join(g for g in (_guard(fn, a, e) for a, e in pairs) if g)
        if not guards:
            continue
        body = "{\n" + guards + "\treturn " + ", ".join(zero_value(r) for r in fn.results) + "\n}"
        if fn.kind == KIND_VAR:
            appended.append(f"var {fn.name} = {fn.signature} {body}")
        else:
            appended.append(f"{fn.signature} {body}")
    if not inserts and not appended:
        return None
    out = parent_src
    for fn, guards in sorted(inserts, key=lambda t: t[0].body_open, reverse=True):
        at = fn.body_open + 1
        rest = out[at:]
        # a one-line body (``{ return a - b }``) must continue on its own line: Go
        # inserts no semicolon between ``}`` and ``return`` on the same line
        splice = guards.rstrip("\n") if rest.startswith("\n") else guards
        out = out[:at] + "\n" + splice + rest
    if appended:
        if not out.strip():
            out = package_clause(gold_src) + "\n"
        block = "\n\n".join(appended)
        out = out.rstrip("\n") + "\n\n" + block + "\n"
        out = add_imports(out, imports_needed(block, gold_src=gold_src, parent_src=parent_src))
    return out


# ---------------------------------------------------------------------------
# env poison: package-level variables re-assigned from init()
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoVar:
    name: str
    decl: str  # the whole ``Name [T] = expr`` spec text
    rhs: str  # the initialiser expression text (``""`` when declared without one)


def _stmt_end(toks: Sequence[Token], j: int) -> int:
    """Index just past the expression starting at ``j`` at depth 0: Go's semicolon
    insertion ends a statement at a newline after an identifier, literal, ``)``,
    ``]`` or ``}``."""
    depth = 0
    k = j
    while k < len(toks):
        t = toks[k]
        if t.kind == KIND_PUNCT and t.text in _OPEN:
            depth += 1
        elif t.kind == KIND_PUNCT and t.text in ")]}":
            depth -= 1
            if depth < 0:
                return k
        nxt = _at(toks, k + 1)
        if depth == 0 and (
            nxt is None
            or (
                nxt.line > t.line
                and (t.kind in (KIND_ID, KIND_NUM, KIND_STR) or t.text in (")", "]", "}"))
            )
            or (nxt.kind == KIND_PUNCT and nxt.text in ";)")
        ):
            return k + 1
        k += 1
    return k


def _var_specs(src: str, specs: Sequence[Token]) -> list[GoVar]:
    """``Name [Type] = expr`` specs (one per line-group) inside a var decl."""
    out: list[GoVar] = []
    j = 0
    while j < len(specs):
        t = specs[j]
        if t.kind != KIND_ID:
            j += 1
            continue
        # one name only (``var a, b = 1, 2`` is skipped — not a single assignable spec)
        k = j + 1
        rhs = ""
        eq = -1
        while k < len(specs):
            s = specs[k]
            if s.kind == KIND_OP and s.text == "=":
                eq = k
                break
            if s.line > t.line and specs[k - 1].kind in (KIND_ID, KIND_NUM, KIND_STR):
                break
            if s.kind == KIND_PUNCT and s.text == ",":
                break
            k += 1
        if eq >= 0:
            end = _stmt_end(specs, eq + 1)
            rhs = src[specs[eq + 1].start : specs[end - 1].end] if end > eq + 1 else ""
            out.append(GoVar(t.text, src[t.start : specs[end - 1].end], rhs))
            j = end
        else:
            out.append(GoVar(t.text, src[t.start : specs[k - 1].end], ""))
            j = k
            if j < len(specs) and specs[j].kind == KIND_PUNCT and specs[j].text == ",":
                j += 1
    return out


def package_vars(src: str) -> dict[str, GoVar]:
    """Top-level ``var`` declarations (single and grouped), keyed by name."""
    toks = sig_tokens(src)
    out: dict[str, GoVar] = {}
    i = 0
    depth = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == KIND_PUNCT and t.text in _OPEN:
            depth += 1
        elif t.kind == KIND_PUNCT and t.text in ")]}":
            depth -= 1
        elif depth == 0 and t.kind == KIND_ID and t.text == "var":
            nxt = _at(toks, i + 1)
            if _is(nxt, "(", KIND_PUNCT):
                k = _match(toks, i + 1)
                if k < 0:
                    break
                for v in _var_specs(src, toks[i + 2 : k]):
                    out.setdefault(v.name, v)
                i = k + 1
                continue
            end = _stmt_end(toks, i + 1)
            for v in _var_specs(src, toks[i + 1 : end]):
                out.setdefault(v.name, v)
            i = max(end, i + 1)
            continue
        i += 1
    return out


def env_poison_file(parent_src: str, gold_src: str) -> tuple[str, tuple[str, ...]]:
    """A NEW non-test file whose ``init()`` re-assigns every package-level variable the
    commit changed to its gold initialiser. Returns ``(text, names)``; raises
    :class:`NotConstructible` when the commit changes no assignable variable."""
    try:
        parent = package_vars(parent_src) if parent_src.strip() else {}
        gold = package_vars(gold_src) if gold_src.strip() else {}
    except ScanError as exc:
        raise NotConstructible(f"source not scannable: {exc}") from exc
    changed = [
        v for name, v in gold.items() if v.rhs and name in parent and parent[name].decl != v.decl
    ]
    if not changed:
        raise NotConstructible(
            "the commit changes no package-level variable the parent declares — Go has no "
            "init-time hook that can replace a plain func, so env_poison cannot be built"
        )
    pkg = package_name(parent_src) or package_name(gold_src)
    assigns = "".join(f"\t{v.name} = {v.rhs}\n" for v in changed)
    body = (
        f"package {pkg}\n\n"
        f"// {ENV_POISON_MARK}: state pollution, not implementation\n"
        f"func init() {{\n{assigns}}}\n"
    )
    needed = imports_needed(assigns, gold_src=gold_src, parent_src="")
    return add_imports(body, needed), tuple(v.name for v in changed)


def describe() -> dict[str, Any]:
    """What this transform family is (for an apparatus stamp)."""
    return {
        "language": LANG_GO,
        "family": "text",
        "stub": "zero-value bodies; added funcs appended; unused imports blank-aliased",
        "regression": "init() panic in an adjacent belt package (new non-test file)",
        "hardcode_cheat": "literal guards from if-got/testify assertions",
        "env_poison": "init() re-assigns changed package-level variables (new non-test file)",
    }
