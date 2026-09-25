"""Belt 6 — ``api_stable``: the public API of the code the builder changed is unchanged,
unless the maintainers' own commit (the gold) changes it the same way.

Why a sixth belt
----------------
Belts 1–4 say the held-out tests accept a patch; belt 5 says the repository's formatter and
linter do. Neither says whether the patch changed what the code PROMISES to its callers. Two
of thirteen reviewed clean patches broke or diverged from the public API — an nhsuk-frontend
blind patch made an optional constructor argument required, and a cobra patch replaced the
exported struct field the maintainers added with an unexported field and an exported setter
(``docs/reviews/2026-09-13-critical-friend.md`` §3.3) **[measured — n = 13 reviewed clean
patches (10 in the review store + 3 cobra), method: human review records, apparatus 2.2]**.
The tests passed because they called what the builder wrote; a reviewer would not merge it.

The rule, exactly
-----------------
For every PUBLIC unit the builder changed — a Go package (a directory), a Python module, a
JavaScript/TypeScript module — the surface (symbol → normalised signature) is read three
times: at the parent, in the trial, and at the gold commit. Every symbol the trial changed
relative to the parent (added, removed or with a different signature) must have been changed
the SAME way by the gold (the gold's signature equals the trial's; both absent counts). A
trial change the gold does not mirror is a finding; any finding fails the belt. A change the
gold made and the trial did not is NOT a finding here — a missing feature is the tests' job.

Deterministic, offline, no model, standard library only: Python by :mod:`ast`; Go and
JavaScript/TypeScript by a small scanner over the source with comments and string contents
blanked (``tests/test_api_surface.py`` cross-checks the Go scanner against ``go/ast`` when a
Go toolchain is present).

What counts as public
---------------------
* **Go** — exported (capitalised) top-level funcs, methods on exported types, types (with
  their exported struct fields and interface methods), vars and consts. Parameter NAMES are
  not API (only types are). ``package main``, ``internal/``, ``testdata/`` and ``vendor/``
  are not public units.
* **Python** — module-level functions, classes (their public and dunder methods, class-level
  annotated attributes), variables and — in ``__init__.py`` or when ``__all__`` names them —
  re-exported imports; ``__all__`` when it is a literal decides the public names, else the
  leading-underscore convention does. Parameter names, kinds and whether a parameter has a
  default are API; annotations and default values are not. A module whose path has a
  ``_private`` component is not a public unit.
* **JavaScript / TypeScript** — ES ``export`` declarations (functions, classes and their
  public methods, bindings, ``export {…}`` lists, re-exports, TS ``interface``/``type``/
  ``enum``) and CommonJS ``module.exports`` / ``exports.x``. A parameter is recorded by its
  SHAPE — plain, optional (has a default or ``?``), rest or destructured — never its name.

Honest limits: the scanners read declarations, not types — a change to an imported type's
own definition in another package is not seen unless that package also changed; a unit whose
source cannot be parsed at one of the three trees is skipped with a named note (not a pass,
not a fail — the belt reads ``None`` when no unit could be evaluated).

Navigation
----------
What it is:   Belt 6 — the public-API surface extractor for Go, Python and JS/TS source, and the
              comparison of the trial's API delta against the gold's (``evaluate``).
What it does: For each public unit a patch changed, reads its surface at parent, trial and gold
              and reports every trial change the gold did not make the same way (``ApiRun``,
              ``ok`` False when any); skips non-public units and unparsable ones with a note.
              Never decides ``clean`` itself and never reads a test file.
How:          ``units_for`` maps changed files to units → ``Trees`` reads each tree (the grader's
              ``WorkspaceTrees`` over the parent, the worktree and the commit) → ``go_surface`` /
              ``python_surface`` / ``js_surface`` → ``compare`` → ``ApiRun``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0021-working-by-construction.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/grade.py (folds ``ApiRun.ok`` into belt 6 when switched on),
              src/crb/core/checks.py (the per-repository switch ``api_stable``),
              src/crb/core/ledger.py (the ``api`` failure kind and the ``api_stable`` row label),
              src/crb/core/workspace.py (the three trees the grader reads)
Tested by:    tests/test_api_surface.py, tests/test_grade_api_belt.py
Touch when:   never for a new repository — switch the belt on per repository with
              ``checks: {api_stable: true}`` (docs/OPERATOR.md); a language gains an extractor
              here with fixture tests in tests/test_api_surface.py and a line in
              docs/adr/0021-working-by-construction.md.
Claims:       ``api_stable = true`` means no trial API change went unmirrored by the gold, as
              far as the declaration scanners see — not that the API is well designed
              (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from crb.core.workspace import Workspace

#: A unit's public surface: symbol → normalised signature.
Surface = dict[str, str]

LANG_GO = "go"
LANG_PYTHON = "python"
LANG_JS = "javascript"

KIND_ADDED = "added"
KIND_REMOVED = "removed"
KIND_CHANGED = "changed"

TREE_PARENT = "parent"
TREE_TRIAL = "trial"
TREE_GOLD = "gold"
TREES: tuple[str, ...] = (TREE_PARENT, TREE_TRIAL, TREE_GOLD)

_JS_EXTS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
#: Path components that never hold a public unit, in any language.
_NON_PUBLIC_DIRS: frozenset[str] = frozenset(
    {
        "internal",
        "testdata",
        "vendor",
        "node_modules",
        "docs",
        "doc",
        "examples",
        "example",
        "scripts",
        "benchmarks",
        "test",
        "tests",
        "__tests__",
        "e2e",
    }
)
_NON_PUBLIC_FILES: frozenset[str] = frozenset(
    {"setup.py", "conftest.py", "noxfile.py", "fabfile.py", "manage.py"}
)
#: Tool configuration and task files, never a module's public API.
_JS_CONFIG_RE = re.compile(r"\.config\.[cm]?[jt]sx?$|^(gulpfile|gruntfile)\.|^\.", re.I)

#: Cap on findings kept on one run (the belt's verdict never depends on it).
MAX_FINDINGS = 50


def language_of(rel: str) -> str:
    """The extractor for ``rel`` by extension (``""`` — not an API source file)."""
    if rel.endswith(".go"):
        return "" if rel.endswith("_test.go") else LANG_GO
    if rel.endswith(".py"):
        return LANG_PYTHON
    if rel.endswith(_JS_EXTS):
        return LANG_JS
    return ""


def is_public_path(rel: str) -> bool:
    """Could ``rel`` hold public API at all? Not under ``internal/``, ``testdata/``,
    ``docs/``… and not a tool/config script; a Python module with a ``_private`` path
    component is private by convention."""
    parts = PurePosixPath(rel).parts
    if any(p in _NON_PUBLIC_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    if name in _NON_PUBLIC_FILES:
        return False
    lang = language_of(rel)
    if lang == LANG_PYTHON:
        return not any(p.startswith("_") and p not in ("__init__.py", "__main__.py") for p in parts)
    if lang == LANG_JS:
        return _JS_CONFIG_RE.search(name) is None
    return lang == LANG_GO


# ---------------------------------------------------------------------------
# Shared scanning helpers (Go and JS): blank comments and string contents
# ---------------------------------------------------------------------------


def _blank(text: str, *, js: bool) -> str:
    """``text`` with comments removed and the CONTENTS of string, rune, raw-string and
    template literals blanked (the quotes kept), newlines preserved — so a brace inside a
    string never unbalances the scan and line structure survives."""
    out: list[str] = []
    i, n = 0, len(text)
    quotes = "\"'`"
    while i < n:
        c = text[i]
        if c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            seg = text[i : n if j < 0 else j + 2]
            out.append("\n" * seg.count("\n") or " ")
            i = n if j < 0 else j + 2
            continue
        if c in quotes:
            raw = c == "`"
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\" and not (raw and not js):
                    j += 2
                    continue
                if text[j] == "\n" and not raw:
                    break
                j += 1
            seg = text[i : j + 1]
            out.append(c + c + "\n" * seg.count("\n"))
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {")", "]", "}"}


def _match(text: str, i: int) -> int:
    """Index just past the bracket that closes the one at ``text[i]`` (``len(text)`` when
    unbalanced — a truncated file reads to its end, never raises)."""
    depth = 0
    for j in range(i, len(text)):
        ch = text[j]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
            if depth == 0:
                return j + 1
    return len(text)


def _split_top(text: str, sep: str = ",") -> list[str]:
    """Split ``text`` at ``sep`` where no bracket is open; empty items dropped."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in text:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


_TOKEN_RE = re.compile(r"\.\.\.|<-|[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*|\d[\w.]*|\S")


def _norm(text: str) -> str:
    """Whitespace-insensitive form of a declaration fragment: one space only between two
    word tokens, none elsewhere (``map[string] int`` and ``map[string]int`` agree)."""
    toks = _TOKEN_RE.findall(text)
    out: list[str] = []
    for t in toks:
        if (
            out
            and (t[0].isalnum() or t[0] in "_$")
            and (out[-1][-1].isalnum() or out[-1][-1] in "_$")
        ):
            out.append(" ")
        out.append(t)
    return "".join(out)


def _top_lines(body: str) -> list[str]:
    """The logical lines of ``body`` at bracket depth 0: a line that opens a bracket
    continues until it closes (a multi-line struct field type, a func literal value)."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in body:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        if ch in "\n;" and depth <= 0:
            line = "".join(cur).strip()
            if line:
                out.append(line)
            cur = []
            depth = max(depth, 0)
            continue
        cur.append(ch)
    line = "".join(cur).strip()
    if line:
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

_GO_KEYWORDS_TYPE = frozenset({"chan", "func", "map", "struct", "interface"})
_IDENT = r"[A-Za-z_][A-Za-z_0-9]*"
_GO_DECL_RE = re.compile(r"^(func|type|var|const)\b", re.M)
_GO_PACKAGE_RE = re.compile(r"^\s*package\s+(" + _IDENT + r")", re.M)


def _exported(name: str) -> bool:
    return bool(name) and name[0].isupper()


def go_package_name(text: str) -> str:
    """The ``package`` clause's name (``""`` when absent)."""
    m = _GO_PACKAGE_RE.search(_blank(text, js=False))
    return m.group(1) if m else ""


def _go_types(params: str) -> str:
    """A Go parameter or result list → its TYPES only (names are not API):
    ``(a, b int, s ...string)`` → ``(int,int,...string)``."""
    inner = params.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    items = _split_top(inner)
    parsed: list[tuple[str, str]] = []  # (name, type) — type "" means a bare token
    named = False
    for item in items:
        m = re.match(r"^(" + _IDENT + r")\s+(\S.*)$", item, re.S)
        if m and m.group(1) not in _GO_KEYWORDS_TYPE:
            parsed.append((m.group(1), m.group(2)))
            named = True
        else:
            parsed.append(("", item))
    types: list[str] = []
    if named:
        pending = ""
        for name, typ in reversed(parsed):
            if name:
                pending = typ
                types.append(typ)
            else:
                types.append(pending)  # a grouped name: ``a, b int`` — ``a`` takes ``int``
        types.reverse()
    else:
        types = [typ for _, typ in parsed]
    return "(" + ",".join(_norm(t) for t in types) + ")"


def _go_func(decl: str) -> tuple[str, str] | None:
    """``func [recv] Name[TP](params) results`` → ``(key, signature)`` or ``None`` when
    unexported / unparsable. A method's key is ``Recv.Name``."""
    s = decl[len("func") :].lstrip()
    recv = ""
    if s.startswith("("):
        end = _match(s, 0)
        recv_text = s[1 : end - 1].strip()
        s = s[end:].lstrip()
        rtoks = recv_text.split()
        rtype = rtoks[-1] if rtoks else ""
        rtype = rtype.lstrip("*").split("[")[0]
        if not _exported(rtype):
            return None
        recv = rtype
    m = re.match(_IDENT, s)
    if not m:
        return None
    name = m.group(0)
    if not _exported(name):
        return None
    s = s[m.end() :].lstrip()
    tparams = ""
    if s.startswith("["):
        end = _match(s, 0)
        tparams = _norm(s[:end])
        s = s[end:].lstrip()
    if not s.startswith("("):
        return None
    end = _match(s, 0)
    params = _go_types(s[:end])
    s = s[end:].lstrip()
    results = ""
    if s.startswith("("):
        end = _match(s, 0)
        results = _go_types(s[:end])
        if len(_split_top(results[1:-1])) == 1:
            results = results[1:-1]  # ``(err error)`` and ``error`` are the same API
    else:
        acc: list[str] = []
        i = 0
        while i < len(s) and s[i] not in "\n{":
            acc.append(s[i])
            i += 1
        text = "".join(acc).rstrip()
        # ``interface{...}`` / ``struct{...}`` as a result type: include its braces
        if i < len(s) and s[i] == "{" and re.search(r"\b(interface|struct)\s*$", text):
            end = _match(s, i)
            text = text + s[i:end]
        results = _norm(text)
    key = f"{recv}.{name}" if recv else name
    return key, f"func{tparams}{params}{results}"


def _go_struct(body: str) -> str:
    """Exported fields (and exported embedded types) of a struct body, sorted; tags and
    unexported fields dropped."""
    fields: list[str] = []
    for raw in _top_lines(body):
        line = re.sub(r'\s*(""|``)\s*$', "", raw).strip()  # a field tag
        if not line:
            continue
        m = re.match(r"^(" + _IDENT + r"(?:\s*,\s*" + _IDENT + r")*)\s+(\S.*)$", line, re.S)
        if m and m.group(1).split(",")[0].strip() not in _GO_KEYWORDS_TYPE:
            typ = _norm(m.group(2))
            for name in (n.strip() for n in m.group(1).split(",")):
                if _exported(name):
                    fields.append(f"{name} {typ}")
            continue
        embedded = line.lstrip("*").split("[")[0].split(".")[-1]
        if _exported(embedded):
            fields.append(f"embed {_norm(line)}")
    return "struct{" + ";".join(sorted(fields)) + "}"


def _go_interface(body: str) -> str:
    """Exported methods and embedded elements of an interface body, sorted."""
    elems: list[str] = []
    for line in _top_lines(body):
        m = re.match(r"^(" + _IDENT + r")\s*\(", line)
        if m:
            fn = _go_func("func " + line)
            if fn is not None:
                elems.append(fn[0] + fn[1][len("func") :])
            continue
        elems.append(_norm(line))
    return "interface{" + ";".join(sorted(elems)) + "}"


def _go_type_expr(expr: str) -> str:
    """A type expression normalised; struct and interface bodies reduced to their
    exported members."""
    e = expr.strip()
    for kw, fn in (("struct", _go_struct), ("interface", _go_interface)):
        if re.match(kw + r"\s*\{", e):
            i = e.index("{")
            end = _match(e, i)
            return fn(e[i + 1 : end - 1])
    return _norm(e)


def _go_type_spec(spec: str) -> tuple[str, str] | None:
    m = re.match(r"^(" + _IDENT + r")", spec)
    if not m or not _exported(m.group(1)):
        return None
    name = m.group(1)
    rest = spec[m.end() :].lstrip()
    tparams = ""
    if rest.startswith("[") and not rest.startswith("[]"):
        end = _match(rest, 0)
        head = rest[:end]
        # ``type T [N]int`` is an array, ``type T[K comparable] …`` a generic type
        if re.search(r"\w\s+\w", head):
            tparams = _norm(head)
            rest = rest[end:].lstrip()
    alias = rest.startswith("=")
    if alias:
        rest = rest[1:].lstrip()
    return name, f"type{tparams}{'=' if alias else ' '}{_go_type_expr(rest)}"


def _go_value_spec(spec: str, kind: str) -> list[tuple[str, str]]:
    m = re.match(r"^(" + _IDENT + r"(?:\s*,\s*" + _IDENT + r")*)", spec)
    if not m:
        return []
    names = [n.strip() for n in m.group(1).split(",")]
    rest = spec[m.end() :].strip()
    typ = ""
    if rest and not rest.startswith("="):
        typ = _norm(_split_top(rest, "=")[0] if "=" in rest else rest)
    sig = f"{kind} {typ}".strip()
    return [(n, sig) for n in names if _exported(n)]


def go_surface(text: str) -> Surface:
    """The exported surface of one Go source file (see the module docstring)."""
    src = _blank(text, js=False)
    out: Surface = {}
    starts = [m.start() for m in _GO_DECL_RE.finditer(src)]
    # a match inside a bracket (a func literal's body line) is not a top-level decl
    depth_at: list[int] = []
    depth = 0
    pos = 0
    for st in starts:
        for ch in src[pos:st]:
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE:
                depth -= 1
        pos = st
        depth_at.append(depth)
    tops = [st for st, d in zip(starts, depth_at, strict=True) if d <= 0]
    for idx, st in enumerate(tops):
        kw = _GO_DECL_RE.match(src, st)
        assert kw is not None
        keyword = kw.group(1)
        after = src[kw.end() :].lstrip()
        if keyword == "func":
            end = tops[idx + 1] if idx + 1 < len(tops) else len(src)
            fn = _go_func(src[st:end])
            if fn is not None:
                out[fn[0]] = fn[1]
            continue
        if after.startswith("("):
            gstart = src.index("(", kw.end())
            gend = _match(src, gstart)
            specs = _top_lines(src[gstart + 1 : gend - 1])
        else:
            line_end = st
            depth = 0
            while line_end < len(src):
                ch = src[line_end]
                if ch in _OPEN:
                    depth += 1
                elif ch in _CLOSE:
                    depth -= 1
                if ch == "\n" and depth <= 0:
                    break
                line_end += 1
            specs = [src[kw.end() : line_end].strip()]
        for spec in specs:
            if keyword == "type":
                t = _go_type_spec(spec)
                if t is not None:
                    out[t[0]] = t[1]
            else:
                for name, sig in _go_value_spec(spec, keyword):
                    out[name] = sig
    return out


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def _py_args(args: ast.arguments) -> str:
    """Parameter names, kinds and default PRESENCE (``=`` suffix); annotations and default
    values are not API."""
    parts: list[str] = []
    pos = [*args.posonlyargs, *args.args]
    n_def = len(args.defaults)
    first_default = len(pos) - n_def
    for i, a in enumerate(pos):
        parts.append(a.arg + ("=" if i >= first_default else ""))
        if args.posonlyargs and i == len(args.posonlyargs) - 1:
            parts.append("/")
    if args.vararg is not None:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parts.append(a.arg + ("=" if d is not None else ""))
    if args.kwarg is not None:
        parts.append("**" + args.kwarg.arg)
    return "(" + ",".join(parts) + ")"


def _py_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    names = []
    for d in node.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Name) and target.id in {
            "staticmethod",
            "classmethod",
            "property",
            "overload",
        }:
            names.append(target.id)
    return ("@" + "@".join(sorted(names)) + " ") if names else ""


def _py_all(tree: ast.Module) -> set[str] | None:
    """A literal ``__all__`` (list/tuple of strings) at module level, else ``None``."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts
            ):
                return {str(e.value) for e in node.value.elts if isinstance(e, ast.Constant)}
            return None
    return None


def _py_public_method(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def _py_class(node: ast.ClassDef, out: Surface) -> None:
    out[node.name] = _py_decorators(node) + "class"
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and _py_public_method(
            item.name
        ):
            asyn = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
            out[f"{node.name}.{item.name}"] = (
                f"{_py_decorators(item)}{asyn}def{_py_args(item.args)}"
            )
        elif (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and not item.target.id.startswith("_")
        ):
            out[f"{node.name}.{item.target.id}"] = "attr" + ("=" if item.value is not None else "")


def _py_body(
    body: Sequence[ast.stmt], out: Surface, public: Callable[[str], bool], reexports: bool
) -> None:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if public(node.name):
                asyn = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                out[node.name] = f"{_py_decorators(node)}{asyn}def{_py_args(node.args)}"
        elif isinstance(node, ast.ClassDef):
            if public(node.name):
                _py_class(node, out)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                names = t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]
                for nm in names:
                    if isinstance(nm, ast.Name) and nm.id != "__all__" and public(nm.id):
                        out.setdefault(nm.id, "var")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if not reexports:
                continue
            mod = level = ""
            if isinstance(node, ast.ImportFrom):
                mod, level = node.module or "", "." * node.level
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if alias.name != "*" and public(name):
                    out[name] = f"import {level}{mod}:{alias.name}"
        elif isinstance(node, ast.If):
            _py_body(node.body, out, public, reexports)
            _py_body(node.orelse, out, public, reexports)
        elif isinstance(node, ast.Try):
            _py_body(node.body, out, public, reexports)
            for h in node.handlers:
                _py_body(h.body, out, public, reexports)
            _py_body(node.orelse, out, public, reexports)


def python_surface(text: str, *, is_package_init: bool = False) -> Surface:
    """The public surface of one Python module (raises ``SyntaxError`` when unparsable)."""
    tree = ast.parse(text)
    declared = _py_all(tree)

    def public(name: str) -> bool:
        return name in declared if declared is not None else not name.startswith("_")

    out: Surface = {}
    _py_body(tree.body, out, public, is_package_init or declared is not None)
    return out


# ---------------------------------------------------------------------------
# JavaScript / TypeScript
# ---------------------------------------------------------------------------


def _js_params(params: str) -> str:
    """A parameter list by SHAPE: ``p`` plain, ``p?`` optional (default or TS ``?``),
    ``...`` rest, ``{}`` / ``[]`` destructured (``?`` when defaulted). Names are not API."""
    inner = params.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    shapes: list[str] = []
    for item in _split_top(inner):
        if item.startswith("..."):
            shapes.append("...")
            continue
        optional = bool(_split_top(item, "=")[1:]) or re.match(r"^[\w$]+\s*\?", item) is not None
        head = item.lstrip()
        base = "{}" if head.startswith("{") else "[]" if head.startswith("[") else "p"
        if head.startswith("this") and re.match(r"^this\s*:", head):
            continue  # a TS ``this`` parameter is not a runtime parameter
        shapes.append(base + ("?" if optional else ""))
    return "(" + ",".join(shapes) + ")"


_JS_FUNC_RE = re.compile(r"^(?:async\s+)?function\s*\*?\s*([\w$]*)\s*(?:<[^>]*>)?\s*\(")
_JS_CLASS_RE = re.compile(r"^(?:abstract\s+)?class\b\s*([\w$]*)[^{]*\{")
_JS_ARROW_RE = re.compile(r"^(?:async\s+)?(\([^)]*\)|[\w$]+)\s*(?::[^=]*)?=>")
_JS_METHOD_RE = re.compile(
    r"^(?:(?:public|protected|private|static|async|readonly|override|abstract|declare|get|set)\s+)*"
    r"(\*?\s*[\w$#]+|\[[^\]]*\])\s*\??\s*(?:<[^>]*>)?\s*\("
)
_JS_MODIFIERS_RE = re.compile(r"^((?:(?:public|protected|private|static|async|get|set)\s+)*)")


def _js_class(body: str) -> dict[str, str]:
    """Public methods of a class body (``#private``, ``_underscore`` and TS ``private``/
    ``protected`` members are not API)."""
    out: dict[str, str] = {}
    for line in _top_lines(body):
        mods = _JS_MODIFIERS_RE.match(line)
        modifiers = mods.group(1).split() if mods else []
        if "private" in modifiers or "protected" in modifiers:
            continue
        m = _JS_METHOD_RE.match(line)
        if not m:
            continue
        name = m.group(1).replace("*", "").strip()
        if name.startswith(("#", "_")):
            continue
        p = line.index("(", m.end() - 1)
        end = _match(line, p)
        tag = " ".join(x for x in modifiers if x in ("static", "get", "set"))
        out[name] = (tag + " " if tag else "") + "method" + _js_params(line[p:end])
    return out


def _js_value_shape(expr: str) -> tuple[str, dict[str, str]]:
    """``(signature, members)`` of an exported value expression: a function or arrow by its
    parameter shapes, a class with its public methods, anything else ``var``."""
    e = expr.strip()
    m = _JS_FUNC_RE.match(e)
    if m:
        p = e.index("(", m.end() - 1)
        return "function" + _js_params(e[p : _match(e, p)]), {}
    m = _JS_CLASS_RE.match(e)
    if m:
        i = e.index("{", m.start())
        return "class", _js_class(e[i + 1 : _match(e, i) - 1])
    m = _JS_ARROW_RE.match(e)
    if m:
        params = m.group(1)
        return "function" + (_js_params(params) if params.startswith("(") else "(p)"), {}
    return "var", {}


def _js_add(out: Surface, name: str, sig: str, members: Mapping[str, str]) -> None:
    out[name] = sig
    for member, msig in members.items():
        out[f"{name}.{member}"] = msig


def js_surface(text: str) -> Surface:
    """The exported surface of one JS/TS module — ES exports and CommonJS exports."""
    src = _blank(text, js=True)
    lines = _top_lines(src)
    local: dict[str, tuple[str, dict[str, str]]] = {}  # top-level declarations by name
    for line in lines:
        body = re.sub(r"^export\s+(default\s+)?", "", line)
        body = re.sub(r"^declare\s+", "", body)
        m = re.match(r"^(?:async\s+)?function\s*\*?\s*([\w$]+)", body)
        if m:
            local[m.group(1)] = _js_value_shape(body)
            continue
        m = re.match(r"^(?:abstract\s+)?class\s+([\w$]+)", body)
        if m:
            local[m.group(1)] = _js_value_shape(body)
            continue
        m = re.match(r"^(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(.*)$", body, re.S)
        if m:
            local[m.group(1)] = _js_value_shape(m.group(2))
    out: Surface = {}
    stars = 0
    for line in lines:
        if line.startswith("export"):
            rest = line[len("export") :].strip()
            if rest.startswith("default"):
                expr = rest[len("default") :].strip()
                ref = re.fullmatch(r"([\w$]+)\s*;?", expr)
                sig, members = (
                    local[ref.group(1)] if ref and ref.group(1) in local else _js_value_shape(expr)
                )
                _js_add(out, "default", sig, members)
                continue
            if rest.startswith("*"):
                # the module path is a blanked string here: count the star re-exports
                stars += 1
                out["*"] = f"reexport-all x{stars}"
                continue
            if rest.startswith("{"):
                inner = rest[1 : _match(rest, 0) - 1]
                from_m = re.search(r"\}\s*from\s*(\S+)", rest)
                for item in _split_top(inner):
                    spec = re.sub(r"^type\s+", "", item)
                    parts = re.split(r"\s+as\s+", spec)
                    orig, name = parts[0].strip(), parts[-1].strip()
                    if from_m:
                        out[name] = "reexport"
                    elif orig in local:
                        _js_add(out, name, *local[orig])
                    else:
                        out[name] = "var"
                continue
            rest = re.sub(r"^declare\s+", "", rest)
            m = re.match(r"^(interface|type|enum|namespace|module)\s+([\w$]+)(.*)$", rest, re.S)
            if m:
                out[m.group(2)] = f"{m.group(1)} {_norm(m.group(3))}"
                continue
            m = re.match(r"^(?:async\s+)?function\s*\*?\s*([\w$]+)", rest) or re.match(
                r"^(?:abstract\s+)?class\s+([\w$]+)", rest
            )
            if m is not None:
                _js_add(out, m.group(1), *_js_value_shape(rest))
                continue
            m = re.match(r"^(?:const|let|var)\s+(.*)$", rest, re.S)
            if m:
                decl = m.group(1)
                if decl.startswith(("{", "[")):
                    for nm in re.findall(r"[\w$]+", decl[: _match(decl, 0)]):
                        out[nm] = "var"
                    continue
                for piece in _split_top(decl):
                    pm = re.match(r"^([\w$]+)\s*(?::[^=]+)?(?:=\s*(.*))?$", piece, re.S)
                    if pm:
                        _js_add(out, pm.group(1), *_js_value_shape(pm.group(2) or ""))
            continue
        m = re.match(r"^(?:module\.)?exports\.([\w$]+)\s*=\s*(.*)$", line, re.S)
        if m:
            _js_add(out, m.group(1), *_resolve_js(m.group(2), local))
            continue
        m = re.match(r"^module\.exports\s*=\s*(.*)$", line, re.S)
        if m:
            expr = m.group(1).strip()
            if expr.startswith("{"):
                inner = expr[1 : _match(expr, 0) - 1]
                for spec in _split_top(inner):
                    kv = re.match(r"^([\w$]+)\s*(?::\s*(.*))?$", spec, re.S)
                    if kv:
                        _js_add(out, kv.group(1), *_resolve_js(kv.group(2) or kv.group(1), local))
            else:
                _js_add(out, "default", *_resolve_js(expr, local))
    return out


def _resolve_js(
    expr: str, local: Mapping[str, tuple[str, dict[str, str]]]
) -> tuple[str, dict[str, str]]:
    """A CommonJS export's value: a local declaration by name, else the expression."""
    ref = re.fullmatch(r"([\w$]+)\s*;?", expr.strip())
    if ref and ref.group(1) in local:
        return local[ref.group(1)]
    return _js_value_shape(expr)


# ---------------------------------------------------------------------------
# The belt: units, trees, comparison
# ---------------------------------------------------------------------------


class Trees(Protocol):
    """Read access to the three trees the belt compares (``parent``, ``trial``, ``gold``)."""

    def read(self, tree: str, rel: str) -> str | None: ...

    def listdir(self, tree: str, directory: str) -> list[str]: ...


@dataclass(frozen=True)
class ApiFinding:
    """One trial API change the gold did not make the same way."""

    unit: str
    symbol: str
    kind: str
    before: str = ""
    after: str = ""
    gold: str = ""

    @property
    def label(self) -> str:
        """``kind:unit:symbol`` — the class signature the prevention loop keys on."""
        return f"{self.kind}:{self.unit}:{self.symbol}"

    def to_dict(self) -> dict[str, str]:
        return {
            "unit": self.unit,
            "symbol": self.symbol,
            "kind": self.kind,
            "before": self.before[:300],
            "after": self.after[:300],
            "gold": self.gold[:300],
        }


@dataclass(frozen=True)
class ApiRun:
    """Belt 6's record on a grade. ``ok``: ``True`` — every trial API change is mirrored
    by the gold (or there was none); ``False`` — at least one finding; ``None`` — no public
    unit could be evaluated (``note`` says why). ``matched`` counts trial changes the gold
    made the same way (a feature the task asked for)."""

    ok: bool | None
    units: tuple[str, ...] = ()
    findings: tuple[ApiFinding, ...] = ()
    matched: int = 0
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "units", tuple(self.units))
        object.__setattr__(self, "findings", tuple(self.findings)[:MAX_FINDINGS])
        # the belt-6 poka-yoke: ``ok`` cannot contradict the findings that produced it
        if self.ok is True and self.findings:
            raise ValueError("an ApiRun cannot be ok with a finding")
        if self.ok is not False and self.findings:
            raise ValueError("findings mean the belt failed (ok=False)")
        if self.ok is False and not self.findings:
            raise ValueError("a failed ApiRun names at least one finding")

    @property
    def label(self) -> str:
        """The row label value: ``true`` / ``false`` / ``none`` (not evaluated)."""
        return "none" if self.ok is None else ("true" if self.ok else "false")

    def summary(self, limit: int = 300) -> str:
        """The findings as one compact, greppable line (the ``api_findings`` row label)."""
        return ";".join(f.label for f in self.findings)[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "units": list(self.units),
            "findings": [f.to_dict() for f in self.findings],
            "matched": self.matched,
            "note": self.note,
        }


def units_for(changed: Sequence[str]) -> dict[str, tuple[str, list[str]]]:
    """``{unit: (language, [changed files])}`` for the PUBLIC units among ``changed``: a Go
    package is its directory, a Python or JS/TS module its file."""
    out: dict[str, tuple[str, list[str]]] = {}
    for rel in changed:
        lang = language_of(rel)
        if not lang or not is_public_path(rel):
            continue
        unit = (os.path.dirname(rel) or ".") if lang == LANG_GO else rel
        out.setdefault(unit, (lang, []))[1].append(rel)
    return out


def _unit_surface(trees: Trees, tree: str, unit: str, lang: str) -> Surface | None:
    """The unit's surface in one tree (``{}`` when the unit does not exist there);
    ``None`` when a file of it could not be parsed, or it is a Go ``main`` package."""
    if lang == LANG_GO:
        out: Surface = {}
        directory = "" if unit == "." else unit
        for rel in sorted(trees.listdir(tree, directory)):
            if not rel.endswith(".go") or rel.endswith("_test.go"):
                continue
            text = trees.read(tree, rel)
            if text is None:
                continue
            if go_package_name(text) == "main":
                return None
            for k, v in go_surface(text).items():
                # a symbol defined per build tag (x_linux.go / x_windows.go): both, joined
                out[k] = v if k not in out or out[k] == v else " | ".join(sorted({out[k], v}))
        return out
    text = trees.read(tree, unit)
    if text is None:
        return {}
    try:
        if lang == LANG_PYTHON:
            return python_surface(text, is_package_init=unit.endswith("__init__.py"))
        return js_surface(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def compare(
    unit: str, parent: Surface, trial: Surface, gold: Surface
) -> tuple[list[ApiFinding], int]:
    """``(findings, matched)``: every symbol whose trial signature differs from the
    parent's is a trial change; it is matched when the gold's signature equals the trial's
    (both absent included), else it is a finding."""
    findings: list[ApiFinding] = []
    matched = 0
    for sym in sorted(set(parent) | set(trial)):
        before, after = parent.get(sym), trial.get(sym)
        if before == after:
            continue
        if gold.get(sym) == after:
            matched += 1
            continue
        kind = KIND_ADDED if before is None else KIND_REMOVED if after is None else KIND_CHANGED
        findings.append(ApiFinding(unit, sym, kind, before or "", after or "", gold.get(sym, "")))
    return findings, matched


def evaluate(changed: Sequence[str], trees: Trees) -> ApiRun:
    """Belt 6 over the trial's changed non-test files (the grader passes belt 4's list)."""
    units = units_for(changed)
    if not units:
        return ApiRun(
            None, note="no public Go, Python or JS/TS unit changed — belt 6 not evaluated"
        )
    findings: list[ApiFinding] = []
    evaluated: list[str] = []
    skipped: list[str] = []
    matched = 0
    for unit, (lang, _files) in sorted(units.items()):
        surfaces = [_unit_surface(trees, t, unit, lang) for t in TREES]
        if any(s is None for s in surfaces):
            skipped.append(unit)
            continue
        p, t, g = (s or {} for s in surfaces)
        found, same = compare(unit, p, t, g)
        findings += found
        matched += same
        evaluated.append(unit)
    note = f"skipped (unparsable or package main): {', '.join(skipped[:5])}" if skipped else ""
    if not evaluated:
        return ApiRun(None, note=note or "no unit could be evaluated")
    return ApiRun(not findings, tuple(evaluated), tuple(findings), matched, note)


class WorkspaceTrees:
    """:class:`Trees` over a grading workspace: the parent commit and the replayed commit
    from the object store (which the builder cannot write), the trial from the worktree."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws

    def _ref(self, tree: str) -> str:
        return self.ws.parent if tree == TREE_PARENT else self.ws.sha

    def read(self, tree: str, rel: str) -> str | None:
        if tree == TREE_TRIAL:
            p = self.ws.root / rel
            try:
                return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
            except OSError:
                return None
        return self.ws.repo.show_file(self._ref(tree), rel)

    def listdir(self, tree: str, directory: str) -> list[str]:
        if tree == TREE_TRIAL:
            d = self.ws.root / directory if directory else self.ws.root
            try:
                return [
                    f"{directory}/{p.name}" if directory else p.name
                    for p in d.iterdir()
                    if p.is_file()
                ]
            except OSError:
                return []
        spec = f"{directory}/" if directory else "."
        res = self.ws.repo.run(
            "ls-tree", "--name-only", self._ref(tree), "--", spec, cwd=self.ws.root
        )
        return [line for line in res.stdout.splitlines() if line] if res.ok else []


__all__ = [
    "KIND_ADDED",
    "KIND_CHANGED",
    "KIND_REMOVED",
    "ApiFinding",
    "ApiRun",
    "Trees",
    "WorkspaceTrees",
    "compare",
    "evaluate",
    "go_package_name",
    "go_surface",
    "is_public_path",
    "js_surface",
    "language_of",
    "python_surface",
    "units_for",
]
