"""Test-infrastructure files: the part of the oracle that is not a test file.

The oracle is the test **run**, not the test **files**. A pytest run executes every
``conftest.py`` on the way to the target, reads the first ``pytest.ini`` /
``pyproject.toml [tool.pytest]`` it finds, imports ``sitecustomize`` from anything on
``PYTHONPATH``; a jest run loads ``jest.config.*`` and the babel transform; ``go test``
honours ``go.mod replace`` and compiles every ``_test.go`` in the package; Maven runs
``./mvnw`` and puts ``src/test/resources`` on the classpath; cargo runs ``build.rs``.
A builder that adds or edits any of those has changed the instrument it is measured
by, and belt 1 (``tests_unmodified``) must fail exactly as it does for an edited
test file. ``[measured]`` the ``env_poison`` negative control — an untouched target
test plus a new root ``conftest.py`` that execs the gold source at collection time —
escaped 3 of 7 times on click before this module existed (critical-friend review,
2026-09-13, §4.3).

Two questions, both pure functions of a repo-relative path and (for the second)
the file's text before and after the builder ran:

* :func:`is_test_infra` — is this path part of the oracle's execution environment
  for this language (and, optionally, this runner)? Answered from
  :data:`INFRA_RULES`, the documented pattern table. Every rule carries the
  *reason* it is oracle-relevant; a rule without a reason is a bug.
* :func:`infra_sections_changed` — for files that are only *partly* oracle-relevant
  (``pyproject.toml``, ``setup.cfg``, ``tox.ini``, ``package.json``, ``go.mod``,
  ``pom.xml``, ``Cargo.toml``) did the edit touch the oracle-relevant sections? A
  version bump or a new runtime dependency is an honest edit; a new
  ``[tool.pytest.ini_options]`` table or ``"jest"`` key is tamper.

Lint configuration is test infrastructure too (ADR-0011 amendment, 2026-09-14)
--------------------------------------------------------------------------------
Belt 5 runs "the repository's own definition of acceptable" — and reads that
definition from the worktree. The independent review pass (finding 2) wrote
``[tool.ruff.lint] select = []`` into ``pyproject.toml``, and separately a nested
``pkg/ruff.toml`` with the same, and turned a ``repo_lint_clean=False`` row into
``CLEAN``. So the files belt 5's detection and the linters themselves read are in
the table: whole-file ``ruff.toml`` / ``.ruff.toml`` / ``.flake8`` /
``.pre-commit-config.yaml`` (ruff evidence), ``.eslintrc*`` / ``eslint.config.*`` /
``.eslintignore`` / ``.prettierrc*`` / ``prettier.config.*`` / ``.prettierignore``
/ ``.editorconfig`` (prettier reads it), ``.golangci.*``, ``rustfmt.toml`` /
``.rustfmt.toml`` / ``clippy.toml`` / ``.clippy.toml``, ``*checkstyle*.xml``; and
section-aware ``pyproject.toml [tool.ruff]``, ``setup.cfg`` / ``tox.ini``
``[flake8]``, ``package.json`` ``eslintConfig`` / ``prettier`` / ``scripts.lint``,
``Cargo.toml [lints]``. Spotless / checkstyle plugin configuration lives in
``pom.xml <build>``, already covered. Touching any of them is belt-1b tamper before
any test runs. ``.editorconfig`` is included for JavaScript only, because prettier
resolves it by default (``indent_size``, ``max_line_length`` change its verdict);
no other belt-5 tool reads it.

Design rules
------------
* **Fail closed.** Anything that cannot be parsed on either side, that is too large
  to parse safely, or that carries an XML DOCTYPE is reported as *changed*. A
  disqualified honest trial is a lost observation; an undisqualified poisoned one
  is a false Q1.
* **Case-insensitive path matching.** ``Conftest.py`` would not be collected on a
  case-sensitive filesystem, but no honest edit produces it either; matching it
  costs nothing and fails closed on case-insensitive hosts.
* **Task test files are the caller's business.** The grader overlays the commit's
  own test files and checks them byte-for-byte (belt 1a); it excludes them before
  asking this module, so a commit whose test files include ``tests/conftest.py`` is
  graded on the overlaid bytes, not disqualified for the harness's own overlay.
* **Runner narrowing is optional.** ``runner=""`` (the default) applies every rule
  for the language — the fail-closed union. Passing the configured runner drops
  rules that runner never reads (``jest.config.*`` under mocha) so an honest edit
  to another tool's config is not a lost observation.

Known residuals (documented, not covered)
-----------------------------------------
* Files a config *references* (jest ``setupFiles``, mocha ``--require``, pytest
  ``pytest_plugins`` modules) are covered only when they match a rule or the
  repo's test layout; the config edit that names a new one is covered.
* ``package.json`` ``exports`` / ``imports`` / ``main`` / ``type`` and ``go.mod``'s
  ``go`` directive are honest edit targets and are not treated as oracle config.
* Python module shadowing through ``runner_opts.pythonpath_suffix`` roots (a
  ``pytest.py`` under ``src/``) — only the repository root is covered.
* Dependency trees (``node_modules``, ``vendor``, ``.venv``) are git-ignored and are
  the sandbox's responsibility (ADR-0005), not belt 1's.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from crb.core.spec import Language

#: Rules for every language (jest/vitest/syrupy snapshot directories and so on).
ANY_LANGUAGE = "*"

#: A section-aware file larger than this is reported as changed without parsing.
MAX_PARSE_BYTES = 2_000_000

#: Sentinel for "this key path is absent" in a plucked document.
_MISSING = object()


# ---------------------------------------------------------------------------
# The pattern table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InfraRule:
    """One row of :data:`INFRA_RULES`.

    ``globs`` are matched against the lower-cased repo-relative POSIX path with
    :func:`fnmatch.fnmatchcase` semantics, where ``*`` also crosses ``/`` — so
    ``*/conftest.py`` means "at any depth ≥ 1" and ``conftest.py`` means "at the
    root". ``runners`` empty means every runner of the language. ``partial`` marks a
    file whose edit is tamper only when :func:`infra_sections_changed` says so.
    """

    language: str
    globs: tuple[str, ...]
    reason: str
    runners: tuple[str, ...] = ()
    partial: bool = False

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(f"infra rule {self.globs} needs a reason")
        object.__setattr__(self, "globs", tuple(g.lower() for g in self.globs))

    def matches(self, rel_lower: str) -> bool:
        return any(fnmatch.fnmatchcase(rel_lower, g) for g in self.globs)


def _anywhere(*names: str) -> tuple[str, ...]:
    """Basename globs at the root and at any depth."""
    return tuple(g for n in names for g in (n, f"*/{n}"))


def _under(*dirs: str) -> tuple[str, ...]:
    """Everything beneath a directory of that name, at the root or at any depth."""
    return tuple(g for d in dirs for g in (f"{d}/*", f"*/{d}/*"))


def _root(*names: str) -> tuple[str, ...]:
    return tuple(names)


_PY = Language.PYTHON.value
_JS = Language.JAVASCRIPT.value
_GO = Language.GO.value
_JVM = Language.JVM.value
_RS = Language.RUST.value

INFRA_RULES: tuple[InfraRule, ...] = (
    # --- every language --------------------------------------------------------
    InfraRule(
        ANY_LANGUAGE,
        _under("__snapshots__"),
        "jest / vitest / syrupy snapshot directories hold the expected values the "
        "target compares against; editing one edits the oracle's expectation",
    ),
    # --- python (pytest) ---------------------------------------------------------
    InfraRule(
        _PY,
        _anywhere("conftest.py"),
        "pytest imports every conftest.py from the rootdir down to the test file at "
        "collection time — arbitrary code runs before the first test",
    ),
    InfraRule(
        _PY,
        _anywhere("pytest.ini", ".pytest.ini"),
        "the first ini file found walking up from the test paths is THE config "
        "(pythonpath, python_files, filterwarnings, usefixtures, required_plugins…); "
        "crb overrides addopts only",
    ),
    InfraRule(
        _PY,
        _anywhere("pyproject.toml"),
        "[tool.pytest] / [tool.pytest.ini_options] is pytest config; "
        "[project.entry-points.pytest11] registers plugins; [tool.ruff] is belt 5's "
        "definition of acceptable (a `select = []` turns a lint rejection into a pass)",
        partial=True,
    ),
    InfraRule(
        _PY,
        _anywhere("setup.cfg"),
        "[tool:pytest] is pytest config; [flake8] is lint config "
        "(section-aware: packaging metadata is not)",
        partial=True,
    ),
    InfraRule(
        _PY,
        _anywhere("tox.ini"),
        "[pytest] is pytest config; [flake8] is lint config "
        "(section-aware: tox environments are not run)",
        partial=True,
    ),
    InfraRule(
        _PY,
        _anywhere("ruff.toml", ".ruff.toml", ".flake8"),
        "ruff reads the closest ruff.toml / .ruff.toml up the tree from each file (a "
        "nested one overrides the root's); flake8 reads .flake8 — belt 5's definition "
        "of acceptable is the repository's, never the builder's (ADR-0011)",
    ),
    InfraRule(
        _PY,
        _anywhere(".pre-commit-config.yaml", ".pre-commit-config.yml"),
        "the ruff-check / ruff-format hooks are the evidence belt 5 detects the "
        "formatter by; removing the hook makes belt 5 not evaluated",
    ),
    InfraRule(
        _PY,
        _anywhere("sitecustomize.py", "usercustomize.py"),
        "imported by `site` at interpreter start from any sys.path entry; the "
        "worktree root (+ pythonpath_suffix) is on PYTHONPATH",
    ),
    InfraRule(
        _PY,
        _anywhere("*.pth"),
        "path-configuration files are executed by `site` (lines starting with "
        "`import` run code); no honest task edit creates one",
    ),
    InfraRule(
        _PY,
        _root("pytest.py", "pytest/*", "_pytest/*", "pluggy/*"),
        "`python -m pytest` resolves the module from the worktree root first: a "
        "root-level shadow replaces the test framework itself (rc=0, nothing run)",
    ),
    InfraRule(
        _PY,
        _anywhere("*.ambr"),
        "syrupy snapshot files are the oracle's expected values",
    ),
    # --- javascript (node --test / vitest / jest / mocha) ---------------------
    InfraRule(
        _JS,
        _anywhere("package.json"),
        '"jest", "mocha" and "babel" are runner config; "scripts.test" (+pre/post) '
        "is the canonical test entry point (not invoked by crb today, kept fail-closed); "
        '"eslintConfig", "prettier" and "scripts.lint" are belt 5\'s lint config',
        partial=True,
    ),
    InfraRule(
        _JS,
        _anywhere(
            ".eslintrc",
            ".eslintrc.*",
            "eslint.config.*",
            ".eslintignore",
            ".prettierrc",
            ".prettierrc.*",
            "prettier.config.*",
            ".prettierignore",
            ".editorconfig",
        ),
        "eslint and prettier read their config (and ignore files) from the tree; "
        "prettier also resolves .editorconfig (indent_size, max_line_length). Belt 5's "
        "definition of acceptable is the repository's, never the builder's (ADR-0011)",
    ),
    InfraRule(
        _JS,
        _anywhere("jest.config.*", "jest-preset.*", "jest.setup.*", "setupTests.*"),
        "jest loads jest.config.{js,ts,mjs,cjs,json,cts,mts} from rootDir; presets, "
        "setup modules and react-scripts' src/setupTests.* run inside the test process",
        runners=("jest",),
    ),
    InfraRule(
        _JS,
        _anywhere("vitest.config.*", "vitest.workspace.*", "vitest.projects.*"),
        "vitest config: setupFiles, globalSetup, environment, resolve.alias",
        runners=("vitest",),
    ),
    InfraRule(
        _JS,
        _anywhere("vite.config.*"),
        "vitest reads the vite config (plugins, resolve.alias and the `test` block "
        "all shape the run); no section-level parse is possible for TS/JS config",
        runners=("vitest",),
    ),
    InfraRule(
        _JS,
        _anywhere(".mocharc", ".mocharc.*", "mocha.opts"),
        "mocha config: require, spec, file, extension, ui, timeout",
        runners=("mocha",),
    ),
    InfraRule(
        _JS,
        _anywhere("babel.config.*", ".babelrc", ".babelrc.*", ".swcrc"),
        "babel-jest / @swc/jest / @babel/register transform every file the run "
        "loads; a transform plugin is arbitrary code",
        runners=("jest", "mocha"),
    ),
    InfraRule(
        _JS,
        _anywhere("tsconfig*.json"),
        "ts-jest and ts-node type-check under this config (a relaxed `strict` turns "
        "a failing compile into a pass); vitest's esbuild reads compilerOptions",
        runners=("jest", "mocha", "vitest"),
    ),
    InfraRule(
        _JS,
        _anywhere("node.config.json"),
        "node's experimental config file (--test-* flags, --import hooks) — not "
        "enabled by default, kept fail-closed",
        runners=("node",),
    ),
    InfraRule(
        _JS,
        _anywhere("*.snap"),
        "jest / vitest snapshot files are the oracle's expected values",
    ),
    # --- go (go test) -----------------------------------------------------------
    InfraRule(
        _GO,
        _anywhere("*_test.go"),
        "`go test` compiles EVERY _test.go in the package: a sibling file's "
        "TestMain (os.Exit(0)) or init() runs inside the target's test binary",
    ),
    InfraRule(
        _GO,
        _under("testdata"),
        "testdata/ is the go convention for golden files and fixtures read by tests",
    ),
    InfraRule(
        _GO,
        _anywhere("go.mod"),
        "replace / exclude redirect the module graph (a local replace points a "
        "dependency at builder-authored code); godebug changes runtime semantics; "
        "require and the go directive are honest edits",
        partial=True,
    ),
    InfraRule(
        _GO,
        _anywhere("go.work"),
        "a workspace file's `use` / `replace` redirect modules for every command",
    ),
    InfraRule(
        _GO,
        _anywhere(".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"),
        "golangci-lint's config enables the formatters/linters belt 5 runs when the "
        "repository declares it (cobra: gofmt + goimports) — the repository's "
        "definition of acceptable, never the builder's (ADR-0011)",
    ),
    # --- jvm (maven / surefire) --------------------------------------------------
    InfraRule(
        _JVM,
        _anywhere("pom.xml"),
        "<build> (surefire config, resources, extensions), <profiles>, <properties> "
        "and <parent> shape the test run; <dependencies> is an honest edit",
        partial=True,
    ),
    InfraRule(
        _JVM,
        _under(".mvn"),
        ".mvn/maven.config and jvm.config inject arguments into every mvn "
        "invocation; extensions.xml loads code into the build",
    ),
    InfraRule(
        _JVM,
        _anywhere("mvnw", "mvnw.cmd"),
        "the runner executes ./mvnw when present — the wrapper IS the test command",
    ),
    InfraRule(
        _JVM,
        _under("src/test"),
        "everything under a Maven test source root is compiled onto the test "
        "classpath or copied to it: static initialisers, junit-platform.properties, "
        "META-INF/services registrations, mockito-extensions, fixture data",
    ),
    InfraRule(
        _JVM,
        _anywhere("META-INF/services/org.junit.*"),
        "JUnit Platform discovers listeners and extensions through ServiceLoader on "
        "the test classpath — main resources included",
    ),
    InfraRule(
        _JVM,
        _anywhere("*checkstyle*.xml"),
        "checkstyle's rule set and suppressions (petclinic: src/checkstyle/"
        "nohttp-checkstyle.xml + -suppressions.xml) are belt 5's definition of "
        "acceptable; the spotless / checkstyle plugin configuration itself is in "
        "pom.xml <build> (section-aware rule above)",
    ),
    # --- rust (cargo test) --------------------------------------------------------
    InfraRule(
        _RS,
        _under("tests"),
        "cargo integration-test roots: sibling helper modules (tests/common/mod.rs) "
        "are compiled into the target binary; non-.rs files are fixtures",
    ),
    InfraRule(
        _RS,
        _anywhere("build.rs"),
        "build scripts run arbitrary code at build time and can rewrite what "
        "include!() pulls into the crate",
    ),
    InfraRule(
        _RS,
        _anywhere("Cargo.toml"),
        "[dev-dependencies], [[test]] (path, harness), [patch], [replace], "
        "[profile.*], package.build/autotests and lib.test/doctest/harness/path "
        "shape the test build; [lints] / [workspace.lints] is clippy's config (belt 5); "
        "[dependencies], [features] and the version are honest",
        partial=True,
    ),
    InfraRule(
        _RS,
        _anywhere("rustfmt.toml", ".rustfmt.toml", "clippy.toml", ".clippy.toml"),
        "cargo fmt --check and cargo clippy read their config from the tree — belt 5's "
        "definition of acceptable is the repository's, never the builder's (ADR-0011)",
    ),
    InfraRule(
        _RS,
        _under(".cargo"),
        ".cargo/config(.toml): rustflags, [env], [patch], paths overrides and a "
        "target `runner` that wraps the test binary",
    ),
    InfraRule(
        _RS,
        _anywhere("rust-toolchain", "rust-toolchain.toml"),
        "a toolchain override switches the compiler under the test",
    ),
    InfraRule(
        _RS,
        _anywhere("*.snap", "*.snap.new"),
        "insta snapshot files are the oracle's expected values",
    ),
)


def _language_value(language: str) -> str:
    if language == ANY_LANGUAGE:
        return ANY_LANGUAGE
    return Language.parse(str(language)).value


def rules_for(language: str, *, runner: str = "") -> tuple[InfraRule, ...]:
    """The rules that apply to ``language`` (plus the cross-language rows), narrowed
    to ``runner`` when one is given. Raises ``ValueError`` for an unknown language."""
    lang = _language_value(language)
    return tuple(
        r
        for r in INFRA_RULES
        if r.language in (ANY_LANGUAGE, lang)
        and (not runner or not r.runners or runner in r.runners)
    )


def _norm(rel_path: str) -> str:
    """Lower-cased POSIX form without a leading ``./`` (dot-files keep their dot)."""
    s = rel_path.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s.lstrip("/").lower()


def matching_rule(rel_path: str, language: str, *, runner: str = "") -> InfraRule | None:
    """The first rule ``rel_path`` matches, or ``None``. Whole-file rules win over
    section-aware ones for the same path (fail closed)."""
    rel = _norm(rel_path)
    hits = [r for r in rules_for(language, runner=runner) if r.matches(rel)]
    if not hits:
        return None
    whole = [r for r in hits if not r.partial]
    return whole[0] if whole else hits[0]


def is_test_infra(rel_path: str, language: str, *, runner: str = "") -> bool:
    """Is ``rel_path`` part of the oracle's execution environment?

    ``True`` for whole-file rules AND for section-aware files (``pyproject.toml``…):
    for the latter the caller decides tamper with :func:`infra_sections_changed`.
    """
    return matching_rule(rel_path, language, runner=runner) is not None


# ---------------------------------------------------------------------------
# Section-aware files
# ---------------------------------------------------------------------------

#: TOML key paths (``*`` = any key at that level) that are oracle-relevant.
_TOML_SECTIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    "pyproject.toml": (
        ("tool", "pytest"),
        ("project", "entry-points", "pytest11"),
        ("tool", "ruff"),  # belt 5 (ADR-0011): the whole [tool.ruff*] tree
    ),
    "cargo.toml": (
        ("dev-dependencies",),
        ("target", "*", "dev-dependencies"),
        ("test",),
        ("patch",),
        ("replace",),
        ("profile",),
        ("package", "build"),
        ("package", "autotests"),
        ("lib", "test"),
        ("lib", "doctest"),
        ("lib", "harness"),
        ("lib", "path"),
        ("lints",),  # belt 5: clippy reads [lints] / [workspace.lints]
        ("workspace", "lints"),
    ),
}

#: INI section names (lower-cased, whitespace stripped) that are pytest or lint config.
_INI_SECTIONS: dict[str, frozenset[str]] = {
    "setup.cfg": frozenset({"tool:pytest", "flake8"}),
    "tox.ini": frozenset({"pytest", "flake8"}),
}

#: ``package.json`` key paths, each with the runners that read it (``()`` = all).
#: The lint keys are runner-independent: belt 5 is orthogonal to the test runner.
_PACKAGE_JSON_SECTIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("jest",), ("jest",)),
    (("mocha",), ("mocha",)),
    (("babel",), ("jest", "mocha")),
    (("scripts", "test"), ()),
    (("scripts", "pretest"), ()),
    (("scripts", "posttest"), ()),
    (("eslintConfig",), ()),
    (("prettier",), ()),
    (("scripts", "lint"), ()),
)

#: go.mod directives that alter what gets built and how it runs.
_GOMOD_DIRECTIVES: frozenset[str] = frozenset({"replace", "exclude", "godebug", "toolchain"})

#: pom.xml top-level children that shape the surefire run.
_POM_SECTIONS: frozenset[str] = frozenset({"build", "profiles", "properties", "parent"})

_XML_UNSAFE_RE = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_INI_COMMENT_CHARS = "#;"


def _pluck(doc: Any, path: Sequence[str]) -> Any:
    """The value at ``path`` in a nested mapping; ``*`` collects every key at that
    level into a dict. :data:`_MISSING` when absent."""
    if not path:
        return doc
    head, rest = path[0], path[1:]
    if not isinstance(doc, Mapping):
        return _MISSING
    if head == "*":
        found = {k: _pluck(v, rest) for k, v in doc.items()}
        found = {k: v for k, v in found.items() if v is not _MISSING}
        return found or _MISSING
    if head not in doc:
        return _MISSING
    return _pluck(doc[head], rest)


def _canon(value: Any) -> str:
    if value is _MISSING:
        return "<missing>"
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _project(doc: Any, paths: Sequence[Sequence[str]]) -> dict[str, str]:
    return {".".join(p): _canon(_pluck(doc, p)) for p in paths}


def _toml_view(text: str, paths: Sequence[Sequence[str]]) -> dict[str, str] | None:
    try:
        doc = tomllib.loads(text) if text.strip() else {}
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    return _project(doc, paths)


def _json_view(text: str, paths: Sequence[Sequence[str]]) -> dict[str, str] | None:
    try:
        doc = json.loads(text) if text.strip() else {}
    except ValueError:
        return None
    if not isinstance(doc, Mapping):
        return None
    return _project(doc, paths)


def _ini_header(line: str) -> str | None:
    s = line.strip()
    if not s.startswith("["):
        return None
    for c in _INI_COMMENT_CHARS:  # iniconfig strips trailing comments on header lines
        s = s.split(c, 1)[0].rstrip()
    if not s.endswith("]"):
        return None
    return "".join(s[1:-1].split()).lower()


def _ini_view(text: str, wanted: frozenset[str]) -> dict[str, str]:
    """Raw text of each wanted section — parser-independent, so a file that
    iniconfig and configparser would read differently still compares honestly."""
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        header = _ini_header(line)
        if header is not None:
            current = header
            if current in wanted:
                bodies.setdefault(current, [])
            continue
        if current in wanted:
            bodies[current].append(line.rstrip())
    return {name: "\n".join(lines).strip() for name, lines in bodies.items()}


def _gomod_view(text: str) -> list[str]:
    """Whitespace-normalised, comment-stripped lines of the wanted directives."""
    out: list[str] = []
    block: str | None = None
    for raw in text.splitlines():
        line = " ".join(raw.split("//", 1)[0].split())
        if not line:
            continue
        if block is not None:
            if line == ")":
                block = None
            elif block in _GOMOD_DIRECTIVES:
                out.append(f"{block} {line}")
            continue
        parts = line.split(" ")
        keyword = parts[0]
        if len(parts) >= 2 and parts[1] == "(":
            block = keyword
            continue
        if keyword in _GOMOD_DIRECTIVES:
            out.append(line)
    return sorted(out)


def _strip_ws(elem: ET.Element) -> None:
    for e in elem.iter():
        if e.text is not None and not e.text.strip():
            e.text = None
        elif e.text is not None:
            e.text = e.text.strip()
        e.tail = None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _xml_view(text: str, wanted: frozenset[str]) -> list[str] | None:
    if not text.strip():
        return []
    if _XML_UNSAFE_RE.search(text):
        return None  # entity expansion: never parse, fail closed
    try:
        root = ET.fromstring(text)  # noqa: S314 — DOCTYPE/ENTITY refused above; no external resolution
    except ET.ParseError:
        return None
    out: list[str] = []
    for child in list(root):
        if _local(child.tag) in wanted:
            _strip_ws(child)
            out.append(ET.tostring(child, encoding="unicode"))
    return sorted(out)


def infra_sections_changed(
    path: str, before_text: str, after_text: str, language: str, *, runner: str = ""
) -> bool:
    """Did an edit to a *partly* oracle-relevant file touch its oracle-relevant part?

    ``before_text`` / ``after_text`` are the file's contents at the parent and in the
    trial worktree; pass ``""`` for "absent" on either side. Returns ``True`` (tamper)
    when the relevant sections differ, when either side fails to parse, when either
    side exceeds :data:`MAX_PARSE_BYTES`, or when ``path`` matches a whole-file rule.
    Returns ``False`` when ``path`` is not test infrastructure at all, or when only
    irrelevant sections (version, dependencies…) changed.
    """
    rule = matching_rule(path, language, runner=runner)
    if rule is None:
        return False
    if not rule.partial:
        return True
    if len(before_text) > MAX_PARSE_BYTES or len(after_text) > MAX_PARSE_BYTES:
        return True
    name = _norm(path).rsplit("/", 1)[-1]
    before: Any
    after: Any
    if name in _TOML_SECTIONS:
        before = _toml_view(before_text, _TOML_SECTIONS[name])
        after = _toml_view(after_text, _TOML_SECTIONS[name])
    elif name in _INI_SECTIONS:
        before = _ini_view(before_text, _INI_SECTIONS[name])
        after = _ini_view(after_text, _INI_SECTIONS[name])
    elif name == "package.json":
        paths = [
            p
            for p, runners in _PACKAGE_JSON_SECTIONS
            if not runner or not runners or runner in runners
        ]
        before = _json_view(before_text, paths)
        after = _json_view(after_text, paths)
    elif name == "go.mod":
        before = _gomod_view(before_text)
        after = _gomod_view(after_text)
    elif name == "pom.xml":
        before = _xml_view(before_text, _POM_SECTIONS)
        after = _xml_view(after_text, _POM_SECTIONS)
    else:  # a partial rule with no section parser is a table bug: fail closed
        return True
    if before is None or after is None:
        return True
    return bool(before != after)


__all__ = [
    "ANY_LANGUAGE",
    "INFRA_RULES",
    "MAX_PARSE_BYTES",
    "InfraRule",
    "infra_sections_changed",
    "is_test_infra",
    "matching_rule",
    "rules_for",
]
