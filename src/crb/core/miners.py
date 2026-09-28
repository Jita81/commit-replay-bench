"""The library's miners — proposals from what a repository already holds, at no model cost.

A person should not have to type what a repository already says. A **miner** reads one kind of
source at one **pinned commit** — the architecture decision records, the code owners and the
directory layout, the lint and formatter configurations, the test layout, the change profile —
and **proposes** library entries (:mod:`crb.core.library`) with their provenance. It never
signs one: a mined proposal is ``proposed`` with no sponsor until a person adopts it, and a
different person signs it (ADR-0026 item 10, DESIGN §9.2 and §9.3).

**The registry is a DL-044 extension seam.** A using team adds a miner by writing a class that
honours :class:`Miner` and calling :func:`register_miner`. The contract, which
:func:`run_miners` enforces on every draft whatever the miner does:

1. A miner has a ``name`` (a slug), a ``version`` (digits; bumped whenever its output for the
   same source changes), the ``kinds`` it proposes and ``reads`` — what it reads, in words.
2. ``mine(source)`` reads only the :class:`MineSource` it is given: the file names and bytes of
   the repository at the pinned commit, the mined tasks and the graded rows. It yields
   :class:`Draft` objects (a proposal) and :class:`Note` objects (a finding it could not
   propose, with its counts). It calls no model and no network: the import contract "crb.core is
   standard-library only" keeps every model SDK and HTTP client out of ``crb.core``.
3. A draft cites its source — one file at the pinned commit (``path``), or graded rows of the
   repository (``rows``) — and never a person. The runner, not the miner, stamps the
   provenance (the commit and the sha256 of the file's bytes there) and ``proposed_by``
   (``mined:<name>@<version>``), so a miner cannot claim a source it did not read or a person
   it is not.
4. A draft is held to the record's rules (:class:`~crb.core.library.LibraryEntry`: a statement
   of at most 400 characters, no code fence, no credential shape in any field). A draft that
   breaks one is refused and named in the run, never written.
5. A draft of a kind the miner did not declare is refused; two drafts of one entry id keep the
   first (registry order); a miner that raises is recorded as failed and the others run.

**Idempotent at a pinned sha.** The same sha proposes nothing new: a draft whose source (the
file and its digest, or the rows) is the one the standing version was proposed from is
``unchanged``. A miner never replaces an entry a person wrote, one a person revoked or retired,
or one a person has adopted while its source is unchanged (``held``); a changed source is a new
version, which needs its two people again.

**Guidance files are data.** ``CLAUDE.md``, ``AGENTS.md`` and ``CONTRIBUTING`` are read only
for the commands they tell a contributor to run, and only a command of a known tool, in a shape
that carries no shell operator, reaches a proposal — inside a fixed sentence. No other word of
them reaches an entry, and no entry reaches a builder's brief outside a measured arm (the import
contract "library entries never reach a brief" names this module).

**Drafting is recorded.** A model may reword a statement (the ``Drafter`` seam, off by default:
no model is called unless an operator passes one). The proposal is then recorded as
``drafted:<model>``, keeps the miner's provenance, and is held to the same rules.

Navigation
----------
What it is:   The miner registry (``Miner``, ``register_miner``), the source a miner reads
              (``MineSource``, ``source_from_git``), the five miners the product ships
              (``adrs``, ``owners``, ``lint``, ``tests``, ``change-profile``) and the runner
              that turns their drafts into library proposals (``run_miners`` → ``MineRun``).
What it does: Reads a repository at a pinned commit; proposes decisions from ADRs, components
              from CODEOWNERS and the directory layout, conventions with their check from
              lint and formatter configurations (and the commands guidance files name), a
              test standard per language from the test layout, and work-type candidates with
              their counts from the change profile; stamps provenance and the proposer; holds
              each draft to the record's rules; and says, per draft, whether it is proposed,
              unchanged, held, refused or only noted.
How:          ``git ls-tree -r`` and ``git cat-file blob`` at the pinned sha through
              ``GitRepo`` (no checkout); each miner is a pure function of the source; the
              runner validates, stamps, compares with the entry's standing state and returns
              the proposals for the caller to append; standard library only (ADR-0008).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 10),
              docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/library.py (the record every proposal is and the state it is
              compared with), src/crb/core/git.py (``GitRepo`` — the pinned tree),
              src/crb/core/taxonomy.py (a work type's global parent),
              src/crb/server/routes/library.py (``POST /library/{repo}/mine`` — appends the
              proposals and events the run), src/crb/cli/commands/library.py (``crb library
              mine`` — the same run over the workdir, printed)
Tested by:    tests/test_miners.py, tests/test_server_routes_library_mine.py,
              tests/test_cli_library.py
Touch when:   never for a new repository — a repository's ADRs, owners, configurations and
              tests are read as they are; a miner is added through ``register_miner`` and
              the contract above (with a test like tests/test_miners.py's added miner); a
              miner's output changes → bump its ``version``; a new source kind a miner may
              cite is a change to ADR-0026 item 10 first.
Claims:       A mined proposal is a reading of a file, not a fact about the code: it counts
              for nothing until two people sign it, and its effect on a builder is
              ``unmeasured`` (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from crb.core.git import GitRepo
from crb.core.library import (
    FINAL_STATUSES,
    KIND_COMPONENT,
    KIND_CONVENTION,
    KIND_DECISION,
    KIND_STANDARD,
    KIND_WORK_TYPE,
    KINDS,
    PROPOSER_DRAFTED,
    PROPOSER_MINED,
    PROVENANCE_FILE,
    PROVENANCE_ROWS,
    STATEMENT_MAX,
    TITLE_MAX,
    EntryState,
    LibraryEntry,
    Provenance,
    is_person,
)
from crb.core.redact import redact
from crb.core.taxonomy import CLASS_DEFINITIONS

MINERS_SCHEMA = "crb.miners.v1"

#: What a run says of each draft.
OUTCOME_PROPOSED = "proposed"
OUTCOME_UNCHANGED = "unchanged"
OUTCOME_HELD = "held"
OUTCOME_REFUSED = "refused"
OUTCOME_NOTED = "noted"
OUTCOME_FAILED = "failed"
OUTCOMES: tuple[str, ...] = (
    OUTCOME_PROPOSED,
    OUTCOME_UNCHANGED,
    OUTCOME_HELD,
    OUTCOME_REFUSED,
    OUTCOME_NOTED,
    OUTCOME_FAILED,
)

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_VERSION_RE = re.compile(r"^[1-9][0-9]{0,5}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
#: The largest file a miner reads (bytes); a larger one is treated as absent.
MAX_FILE_BYTES = 512_000
#: The ISO/IEC 25010:2023 characteristics the shipped miners name.
MAINTAINABILITY = "Maintainability"
FUNCTIONAL_SUITABILITY = "Functional suitability"
#: Belt 5's check: the linter or formatter the repository configures, run on the change.
CHECK_LINT = "repo_lint_clean"
#: Belt 2's check: the target test, failing before the change, passes after it.
CHECK_TARGET = "target_green"


# ---------------------------------------------------------------------------
# What a miner reads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MinedTask:
    """A mined commit as the change profile reads it: its class, size and the files it
    changed (source and tests)."""

    task_id: str
    capability_class: str
    size: str = ""
    src_files: tuple[str, ...] = ()
    test_files: tuple[str, ...] = ()

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any]) -> MinedTask:
        """From a ``TaskSpec`` dictionary (``tasks.spec_json`` or a workdir task line)."""
        return cls(
            task_id=str(spec.get("task_id", "")),
            capability_class=str(spec.get("capability_class", "")),
            size=str(spec.get("size", "")),
            src_files=tuple(str(p) for p in spec.get("src_files") or ()),
            test_files=tuple(str(p) for p in spec.get("test_files") or ()),
        )


@dataclass(frozen=True)
class GradedRow:
    """A graded row as the change profile cites it: its hash, its commit and its verdict."""

    row_hash: str
    task_id: str
    clean: bool


class MineSource:
    """One repository at one pinned commit, read-only: its file names, the bytes of any file
    (read once, cached, at most :data:`MAX_FILE_BYTES`), the mined tasks and the graded rows.
    ``files_read`` is every path a miner asked for — the run records it."""

    def __init__(
        self,
        repo: str,
        commit: str,
        files: Iterable[str],
        read: Callable[[str], bytes | None],
        *,
        tasks: Iterable[MinedTask] = (),
        graded: Iterable[GradedRow] = (),
    ) -> None:
        if not repo.strip():
            raise ValueError("a mine names its repository")
        if not _FULL_SHA_RE.match(commit):
            raise ValueError("a mine is pinned to one commit: its full 40-character sha")
        self.repo = repo
        self.commit = commit
        self.files: tuple[str, ...] = tuple(sorted(set(files)))
        self._present = frozenset(self.files)
        self._read = read
        self._cache: dict[str, bytes | None] = {}
        self.tasks: tuple[MinedTask, ...] = tuple(tasks)
        self.graded: tuple[GradedRow, ...] = tuple(graded)
        self._roots: tuple[str, ...] | None = None

    def has(self, path: str) -> bool:
        return path in self._present

    def blob(self, path: str) -> bytes | None:
        """The file's bytes at the commit, or ``None`` when it is absent or too large."""
        if path not in self._present:
            return None
        if path not in self._cache:
            data = self._read(path)
            self._cache[path] = data if data is not None and len(data) <= MAX_FILE_BYTES else None
        return self._cache[path]

    def text(self, path: str) -> str | None:
        data = self.blob(path)
        return None if data is None else data.decode("utf-8", errors="replace")

    def digest(self, path: str) -> str | None:
        data = self.blob(path)
        return None if data is None else hashlib.sha256(data).hexdigest()

    @property
    def files_read(self) -> tuple[str, ...]:
        return tuple(sorted(self._cache))

    @property
    def component_roots(self) -> tuple[str, ...]:
        if self._roots is None:
            self._roots = component_roots(self.files)
        return self._roots


def list_files(git: GitRepo, commit: str) -> list[str]:
    """Every file path in the tree of ``commit`` (``git ls-tree -r -z``; no checkout)."""
    out = git.run("ls-tree", "-r", "-z", "--name-only", commit, check=True).stdout
    return [p for p in out.split("\0") if p]


def source_from_git(
    git: GitRepo,
    repo: str,
    ref: str,
    *,
    tasks: Iterable[MinedTask] = (),
    graded: Iterable[GradedRow] = (),
) -> MineSource:
    """The source for ``repo`` at ``ref``, pinned to the full sha ``ref`` names now — a
    branch that moves later does not move the mine. Raises ``GitError`` when ``ref`` names no
    commit of the clone."""
    commit = git.rev_parse(ref)
    return MineSource(
        repo,
        commit,
        list_files(git, commit),
        lambda path: git.show_blob(commit, path),
        tasks=tasks,
        graded=graded,
    )


# ---------------------------------------------------------------------------
# What a miner yields
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Draft:
    """A proposal as a miner writes it: the entry's fields and the source it cites — one file
    at the pinned commit (``path``) or graded rows (``rows``). The runner stamps the
    provenance and the proposer."""

    kind: str
    slug: str
    title: str
    statement: str
    path: str = ""
    rows: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    work_types: tuple[str, ...] = ()
    characteristic: str = ""
    check: str = ""
    parent_class: str = ""
    examples: tuple[str, ...] = ()
    slots: tuple[str, ...] = ()

    @property
    def entry_id(self) -> str:
        return f"{self.kind}/{self.slug}"


@dataclass(frozen=True)
class Note:
    """A finding a miner could not propose — why, and its counts (a work-type candidate
    with no graded rows to cite, a component with no file to cite)."""

    subject: str
    reason: str
    counts: Mapping[str, int] = field(default_factory=dict)


Finding = Draft | Note


@runtime_checkable
class Miner(Protocol):
    """The contract every miner honours (the module docstring's five clauses)."""

    name: str
    version: str
    kinds: tuple[str, ...]
    reads: str

    def mine(self, source: MineSource) -> Iterable[Finding]: ...


@dataclass(frozen=True)
class Drafter:
    """SEAM (off by default): a model that rewords a mined statement. ``name`` is the model
    the proposal is recorded under (``drafted:<name>``); ``draft`` takes the draft and returns
    its statement. Only an operator's explicit choice passes one; nothing in the product does
    by default."""

    name: str
    draft: Callable[[Draft], str]


def proposer_of(miner: Miner) -> str:
    """``mined:<name>@<version>`` — the proposer a miner's proposals are recorded under."""
    return f"{PROPOSER_MINED}{miner.name}@{miner.version}"


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Miner] = {}


def _check_miner(miner: Miner) -> None:
    if not isinstance(miner, Miner):
        raise TypeError("a miner has name, version, kinds, reads and mine(source)")
    if not _NAME_RE.match(str(miner.name)):
        raise ValueError(f"a miner's name is a lower-case slug of at most 32: {miner.name!r}")
    if not _VERSION_RE.match(str(miner.version)):
        raise ValueError(f"a miner's version is a positive whole number: {miner.version!r}")
    kinds = tuple(miner.kinds)
    if not kinds or any(k not in KINDS for k in kinds):
        raise ValueError(f"a miner proposes one or more of {KINDS}: {kinds!r}")
    if not str(miner.reads).strip():
        raise ValueError("a miner says what it reads")


def register_miner(miner: Miner, *, replace: bool = False) -> Miner:
    """Add ``miner`` to the registry (checked against the contract); ``ValueError`` when the
    name is taken, unless ``replace``. Returns the miner, so it can decorate an instance."""
    _check_miner(miner)
    if miner.name in _REGISTRY and not replace:
        raise ValueError(f"a miner named {miner.name!r} is already registered")
    _REGISTRY[miner.name] = miner
    return miner


def unregister_miner(name: str) -> None:
    """Remove a miner (a using team's test, or a miner withdrawn); unknown names are ignored."""
    _REGISTRY.pop(name, None)


def miner_names() -> tuple[str, ...]:
    """Every registered miner, in registration order (the order a run applies them)."""
    return tuple(_REGISTRY)


def get_miner(name: str) -> Miner:
    try:
        return _REGISTRY[name]
    except KeyError as e:
        raise ValueError(f"no miner registered as {name!r}; one of {miner_names()}") from e


def describe_miners() -> list[dict[str, Any]]:
    """The registry as data: name, version, proposer, kinds and what each reads."""
    return [
        {
            "name": m.name,
            "version": m.version,
            "proposer": proposer_of(m),
            "kinds": list(m.kinds),
            "reads": m.reads,
        }
        for m in _REGISTRY.values()
    ]


# ---------------------------------------------------------------------------
# Shared readings
# ---------------------------------------------------------------------------

#: Directories that group components one level down.
CONTAINER_DIRS = frozenset(
    {"src", "lib", "libs", "packages", "apps", "services", "modules", "crates", "cmd",
     "internal", "pkg", "components", "plugins"}
)  # fmt: skip
#: Top-level directories that are not parts of the system (tests, docs, vendored or built).
NOT_COMPONENTS = frozenset(
    {"test", "tests", "spec", "specs", "__tests__", "testdata", "e2e", "doc", "docs",
     "node_modules", "vendor", "third_party", "dist", "build", "target", "out"}
)  # fmt: skip


def component_roots(files: Iterable[str]) -> tuple[str, ...]:
    """The directory layout's components: each top-level directory, or one level below a
    container (``src/``, ``packages/``, ``cmd/`` …), leaving out hidden, test, documentation,
    vendored and built directories."""
    roots: set[str] = set()
    for path in files:
        parts = path.split("/")
        if len(parts) < 2:
            continue
        top = parts[0]
        if top.startswith(".") or top in NOT_COMPONENTS:
            continue
        if top in CONTAINER_DIRS and len(parts) >= 3 and not parts[1].startswith("."):
            roots.add(f"{top}/{parts[1]}")
        else:
            roots.add(top)
    return tuple(sorted(roots))


def component_of(path: str, roots: Sequence[str]) -> str:
    """The component ``path`` belongs to (the longest root it sits under), or ``""``."""
    best = ""
    for root in roots:
        if path.startswith(root + "/") and len(root) > len(best):
            best = root
    return best


def slugify(text: str, *, limit: int = 64) -> str:
    """A library slug from free text: lower case, runs of anything else as ``-``."""
    s = re.sub(r"[^a-z0-9._]+", "-", text.lower()).strip("-._")
    s = s[:limit].rstrip("-._")
    return s or "x"


def fit(text: str, limit: int = STATEMENT_MAX) -> str:
    """``text`` with its whitespace collapsed, cut at a word before ``limit`` with an
    ellipsis when it is longer."""
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    cut = t[: limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(" ,;:") + "…"


# ---------------------------------------------------------------------------
# Miner 1: ADRs → decisions
# ---------------------------------------------------------------------------

_ADR_DIR_RE = re.compile(
    r"(^|/)(adr|adrs|decisions|decision-records|architecture-decisions|"
    r"architecture/decisions)/",
    re.I,
)
_ADR_FILE_RE = re.compile(r"^(adr[-_]?)?(\d{1,5})[-_. ].*\.md$", re.I)
_STATUS_LINE_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?[*_]*status[*_]*\s*[:\uff1a]\s*[*_]*\s*([A-Za-z-]+)", re.I | re.M
)
_STATUS_HEAD_RE = re.compile(r"^#{2,4}\s*status\s*$", re.I | re.M)
_TITLE_PREFIX_RE = re.compile(r"^(adr[-\s]?)?\d{1,5}\s*[:.\-\u2013\u2014]?\s*", re.I)
#: Statuses of a decision in force; any other stated status is not proposed.
IN_FORCE = frozenset({"accepted", "approved", "adopted", "active", "decided", "agreed"})
#: A section whose heading starts so holds the decision ("Decision", "Decision outcome",
#: "Decision — the rule").
_DECISION_HEADS = ("decision", "the decision")


def _markdown_sections(text: str) -> tuple[str, dict[str, list[str]], list[str]]:
    """``(title, {heading: lines}, lines before the first second-level heading)`` with
    fenced code removed."""
    title = ""
    sections: dict[str, list[str]] = {}
    preamble: list[str] = []
    current: list[str] | None = None
    fenced = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        head = re.match(r"^##\s+(.*)$", line)
        if head:
            current = sections.setdefault(head.group(1).strip().lower().rstrip(":"), [])
            continue
        if line.startswith("###"):
            continue  # a subsection stays inside its section
        (preamble if current is None else current).append(line)
    return title, sections, preamble


def _first_paragraph(lines: Sequence[str], *, skip_metadata: bool = False) -> str:
    """The first paragraph of ``lines``: tables, comments and rules skipped, and — in a
    record's preamble — ``Key: value`` metadata lines (``Date:``, ``Deciders:``)."""
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            if out:
                break
            continue
        meta = skip_metadata and re.match(r"^(?:[-*+]\s+)?[*_]*\w[\w ]{0,20}[*_]*\s*:", s)
        if s.startswith(("|", "<!--", "---")) or meta:
            if out:
                break
            continue
        out.append(re.sub(r"^[-*+]\s+|^\d+\.\s+", "", s))
    return " ".join(out)


def _adr_status(text: str, sections: Mapping[str, list[str]]) -> str:
    m = _STATUS_LINE_RE.search(text)
    if m:
        return m.group(1).lower()
    if _STATUS_HEAD_RE.search(text):
        for line in sections.get("status", []):
            word = re.sub(r"[^A-Za-z-]", " ", line).split()
            if word:
                return word[0].lower()
    return ""


class AdrMiner:
    """Architecture decision records → ``decision`` entries: each ADR in force, with its
    decision's first paragraph and the components its text names."""

    name = "adrs"
    version = "1"
    kinds: tuple[str, ...] = (KIND_DECISION,)
    reads = (
        "architecture decision records (docs/adr/NNNN-*.md and the like): title, status and "
        "the first paragraph of the decision"
    )

    def mine(self, source: MineSource) -> Iterator[Finding]:
        for path in source.files:
            base = path.rsplit("/", 1)[-1]
            if not _ADR_DIR_RE.search(path) or not _ADR_FILE_RE.match(base):
                continue
            if "template" in base.lower():
                continue
            text = source.text(path)
            if text is None:
                continue
            named = _ADR_FILE_RE.match(base)
            number = named.group(2) if named else "?"
            title, sections, preamble = _markdown_sections(text)
            title = _TITLE_PREFIX_RE.sub("", title).strip() or base[:-3]
            status = _adr_status(text, sections)
            if status and status not in IN_FORCE:
                yield Note(path, f"not in force: its status is {status}")
                continue
            body = next(
                (lines for h, lines in sections.items() if h.startswith(_DECISION_HEADS)), None
            )
            decided = (
                _first_paragraph(body)
                if body is not None
                else _first_paragraph(preamble, skip_metadata=True)
            )
            if not decided:
                yield Note(path, "no decision text to state")
                continue
            said = f"ADR {number} ({status or 'no status stated'}): {decided}"
            bound = tuple(
                slugify(r.replace("/", "-"))
                for r in source.component_roots
                if re.search(rf"(?<![\w./-]){re.escape(r)}/", text) or f"`{r}`" in text
            )
            yield Draft(
                kind=KIND_DECISION,
                slug=slugify(f"adr-{number}-{title}"),
                title=fit(f"ADR {number}: {title}", TITLE_MAX),
                statement=fit(said),
                path=path,
                components=tuple(dict.fromkeys(bound))[:32],
            )


# ---------------------------------------------------------------------------
# Miner 2: CODEOWNERS and the directory layout → components
# ---------------------------------------------------------------------------

CODEOWNERS_PATHS: tuple[str, ...] = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
#: The file that makes a directory a part, in the order one is cited.
MARKERS: tuple[str, ...] = (
    "README.md", "README", "README.rst", "package.json", "pyproject.toml", "setup.py",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "__init__.py",
    "index.ts", "index.js", "mod.rs", "lib.rs", "main.go", "doc.go",
)  # fmt: skip
_HANDLE_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9_.-]+)?$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _glob_re(pattern: str) -> re.Pattern[str]:
    p = pattern.strip()
    anchored = p.startswith("/") or "/" in p.strip("/")
    p = p.strip("/")
    body = ""
    i = 0
    while i < len(p):
        if p.startswith("**", i):
            body += ".*"
            i += 2
        elif p[i] == "*":
            body += "[^/]*"
            i += 1
        elif p[i] == "?":
            body += "[^/]"
            i += 1
        else:
            body += re.escape(p[i])
            i += 1
    if p in ("", "*", "**"):
        return re.compile(r"^.*$")
    prefix = "^" if anchored else r"^(?:.*/)?"
    return re.compile(prefix + body + r"(?:/.*)?$")


def parse_codeowners(text: str) -> list[tuple[re.Pattern[str], tuple[str, ...], int]]:
    """``(pattern, owners, emails)`` per rule, in file order. Owners are ``@handle`` or
    ``@org/team``; an email address is counted, never copied."""
    rules = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        owners = tuple(o for o in parts[1:] if _HANDLE_RE.match(o))
        emails = sum(1 for o in parts[1:] if _EMAIL_RE.match(o))
        rules.append((_glob_re(parts[0]), owners, emails))
    return rules


class OwnersMiner:
    """CODEOWNERS and the directory layout → ``component`` entries: each part of the system,
    its file count at the commit and the owners CODEOWNERS names for it."""

    name = "owners"
    version = "1"
    kinds: tuple[str, ...] = (KIND_COMPONENT,)
    reads = "CODEOWNERS (the root, .github/ or docs/) and the directory layout at the commit"

    def mine(self, source: MineSource) -> Iterator[Finding]:
        owners_path = next((p for p in CODEOWNERS_PATHS if source.has(p)), "")
        owners_text = source.text(owners_path) if owners_path else None
        rules = parse_codeowners(owners_text) if owners_text is not None else []
        seen: set[str] = set()
        for root in source.component_roots:
            n = sum(1 for f in source.files if f.startswith(root + "/"))
            matched = [(o, e) for rx, o, e in rules if rx.match(root) or rx.match(root + "/")]
            owners, emails = matched[-1] if matched else ((), 0)
            if owners or emails:
                cited = owners_path
                named = ", ".join(owners) if owners else ""
                if emails:
                    extra = f"{emails} email address{'es' if emails != 1 else ''}"
                    named = f"{named} and {extra}" if named else extra
                said = f"Owners: {named}, per {owners_path}."
            else:
                cited = next((f"{root}/{m}" for m in MARKERS if source.has(f"{root}/{m}")), "")
                said = (
                    f"{owners_path} names no owner for it."
                    if owners_path
                    else "The repository has no CODEOWNERS file."
                )
            if not cited:
                yield Note(root, "no CODEOWNERS rule, manifest or README to cite", {"files": n})
                continue
            slug = slugify(root.replace("/", "-"))
            if slug in seen:
                yield Note(root, f"its slug {slug} is taken by another part", {"files": n})
                continue
            seen.add(slug)
            yield Draft(
                kind=KIND_COMPONENT,
                slug=slug,
                title=fit(f"Component {root}", TITLE_MAX),
                statement=fit(f"The part of the system under {root}/. {said}"),
                path=cited,
            )


# ---------------------------------------------------------------------------
# Miner 3: lint and formatter configurations (and guidance files) → conventions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tool:
    tool: str
    role: str  # "linter" | "formatter" | "type checker"
    command: str
    belt5: bool  # crb's belt 5 runs it where the repository configures it


_TOOLS: dict[str, _Tool] = {
    t.tool: t
    for t in (
        _Tool("ruff", "linter", "ruff check", True),
        _Tool("ruff-format", "formatter", "ruff format --check", True),
        _Tool("black", "formatter", "black --check", True),
        _Tool("isort", "formatter", "isort --check-only", False),
        _Tool("flake8", "linter", "flake8", False),
        _Tool("pylint", "linter", "pylint", False),
        _Tool("mypy", "type checker", "mypy", False),
        _Tool("eslint", "linter", "eslint", True),
        _Tool("prettier", "formatter", "prettier --check", True),
        _Tool("stylelint", "linter", "stylelint", True),
        _Tool("biome", "linter", "biome check", False),
        _Tool("tsc", "type checker", "tsc --noEmit", True),
        _Tool("gofmt", "formatter", "gofmt -l", True),
        _Tool("golangci-lint", "linter", "golangci-lint run", False),
        _Tool("cargo-fmt", "formatter", "cargo fmt --check", True),
        _Tool("clippy", "linter", "cargo clippy", True),
        _Tool("spotless", "formatter", "mvn spotless:check", True),
        _Tool("checkstyle", "linter", "mvn checkstyle:check", True),
        _Tool("rubocop", "linter", "rubocop", False),
        _Tool("clang-format", "formatter", "clang-format --dry-run", False),
        _Tool("editorconfig", "formatter", "an EditorConfig checker", False),
        _Tool("pre-commit", "linter", "pre-commit run --all-files", False),
    )
}

_ESLINT_FILES = (
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml",
    ".eslintrc.yaml", "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
    "eslint.config.ts",
)  # fmt: skip
_PRETTIER_FILES = (
    ".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.yml",
    ".prettierrc.yaml", ".prettierrc.toml", "prettier.config.js", "prettier.config.cjs",
    "prettier.config.mjs",
)  # fmt: skip
_STYLELINT_FILES = (".stylelintrc", ".stylelintrc.json", "stylelint.config.js")


def _has_table(text: str | None, *tables: str) -> bool:
    if not text:
        return False
    return any(re.search(rf"^\s*\[{re.escape(t)}[\].]", text, re.M) for t in tables)


def _precommit_hook(text: str | None, hook: str) -> bool:
    return (
        bool(text)
        and re.search(rf"^\s*-\s*id:\s*{re.escape(hook)}\s*$", text or "", re.M) is not None
    )


def detect_tools(source: MineSource) -> dict[str, str]:
    """tool → the file at the commit that configures it (the first found, in a fixed order)."""
    found: dict[str, str] = {}

    def first(tool: str, *paths: str) -> None:
        if tool not in found:
            hit = next((p for p in paths if source.has(p)), "")
            if hit:
                found[tool] = hit

    pyproject = source.text("pyproject.toml") if source.has("pyproject.toml") else None
    setup_cfg = source.text("setup.cfg") if source.has("setup.cfg") else None
    tox_ini = source.text("tox.ini") if source.has("tox.ini") else None
    precommit = (
        source.text(".pre-commit-config.yaml") if source.has(".pre-commit-config.yaml") else None
    )
    ruff_toml = next((p for p in ("ruff.toml", ".ruff.toml") if source.has(p)), "")
    if ruff_toml:
        found["ruff"] = ruff_toml
        if _has_table(source.text(ruff_toml), "format"):
            found["ruff-format"] = ruff_toml
    if _has_table(pyproject, "tool.ruff"):
        found.setdefault("ruff", "pyproject.toml")
        if _has_table(pyproject, "tool.ruff.format"):
            found.setdefault("ruff-format", "pyproject.toml")
    if _precommit_hook(precommit, "ruff") or _precommit_hook(precommit, "ruff-check"):
        found.setdefault("ruff", ".pre-commit-config.yaml")
    if _precommit_hook(precommit, "ruff-format"):
        found.setdefault("ruff-format", ".pre-commit-config.yaml")
    if _has_table(pyproject, "tool.black"):
        found["black"] = "pyproject.toml"
    elif _precommit_hook(precommit, "black"):
        found["black"] = ".pre-commit-config.yaml"
    first("isort", ".isort.cfg")
    if "isort" not in found and _has_table(pyproject, "tool.isort"):
        found["isort"] = "pyproject.toml"
    first("flake8", ".flake8")
    for path, text in (("setup.cfg", setup_cfg), ("tox.ini", tox_ini)):
        if "flake8" not in found and _has_table(text, "flake8"):
            found["flake8"] = path
    first("pylint", ".pylintrc", "pylintrc")
    if "pylint" not in found and _has_table(pyproject, "tool.pylint"):
        found["pylint"] = "pyproject.toml"
    first("mypy", "mypy.ini", ".mypy.ini")
    if "mypy" not in found and _has_table(pyproject, "tool.mypy"):
        found["mypy"] = "pyproject.toml"
    if "mypy" not in found and _has_table(setup_cfg, "mypy"):
        found["mypy"] = "setup.cfg"
    first("eslint", *_ESLINT_FILES)
    first("prettier", *_PRETTIER_FILES)
    first("stylelint", *_STYLELINT_FILES)
    first("biome", "biome.json", "biome.jsonc")
    pkg = source.text("package.json") if source.has("package.json") else None
    if source.has("tsconfig.json") and pkg and re.search(r'":\s*"[^"]*\btsc\b', pkg):
        found["tsc"] = "tsconfig.json"
    first("gofmt", "go.mod")
    first("golangci-lint", ".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")
    first("cargo-fmt", "rustfmt.toml", ".rustfmt.toml")
    first("clippy", "clippy.toml", ".clippy.toml")
    pom = source.text("pom.xml") if source.has("pom.xml") else None
    if pom and "spotless-maven-plugin" in pom:
        found["spotless"] = "pom.xml"
    if pom and "maven-checkstyle-plugin" in pom:
        found["checkstyle"] = "pom.xml"
    first("rubocop", ".rubocop.yml")
    first("clang-format", ".clang-format")
    first("editorconfig", ".editorconfig")
    first("pre-commit", ".pre-commit-config.yaml")
    return found


#: Files a contributor's guidance lives in: read as data, never injected (DESIGN §9.2).
GUIDANCE_FILES: tuple[str, ...] = (
    "CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "CONTRIBUTING.rst",
    "CONTRIBUTING.txt", "CONTRIBUTING", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md",
)  # fmt: skip
#: A command as a guidance file may name one: words, flags and paths — never a shell
#: operator, a quote, a substitution or a redirection.
_COMMAND_RE = re.compile(r"^[a-z][a-z0-9._-]*( [A-Za-z0-9._/:=@+,-]+){0,6}$")
_RUNNERS = ("npx ", "python -m ", "python3 -m ", "uv run ", "poetry run ", "pipx run ")
#: The leading words of a command → the tool it runs (only these reach a proposal).
_COMMAND_TOOLS: tuple[tuple[str, str], ...] = (
    ("ruff format", "ruff-format"),
    ("ruff check", "ruff"),
    ("ruff", "ruff"),
    ("black", "black"),
    ("isort", "isort"),
    ("flake8", "flake8"),
    ("pylint", "pylint"),
    ("mypy", "mypy"),
    ("eslint", "eslint"),
    ("prettier", "prettier"),
    ("stylelint", "stylelint"),
    ("biome", "biome"),
    ("tsc", "tsc"),
    ("gofmt", "gofmt"),
    ("golangci-lint", "golangci-lint"),
    ("cargo fmt", "cargo-fmt"),
    ("cargo clippy", "clippy"),
    ("rubocop", "rubocop"),
    ("clang-format", "clang-format"),
    ("pre-commit", "pre-commit"),
)
_CODE_SPAN_RE = re.compile(r"`([^`\n]{1,120})`")


def guidance_commands(text: str) -> list[tuple[str, str]]:
    """``(tool, command)`` for each command of a known tool the text names — in a code span
    or a fenced line — in the order found, first per tool. Anything else is dropped: prose,
    instructions, URLs and any command carrying a shell operator never leave this function."""
    candidates: list[str] = [m.group(1) for m in _CODE_SPAN_RE.finditer(text)]
    fenced = False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            candidates.append(s.removeprefix("$ ").strip())
    out: dict[str, str] = {}
    for c in candidates:
        cmd = " ".join(c.split())
        if not _COMMAND_RE.match(cmd):
            continue
        bare = cmd
        for runner in _RUNNERS:
            if bare.startswith(runner):
                bare = bare[len(runner) :]
                break
        for lead, tool in _COMMAND_TOOLS:
            if bare == lead or bare.startswith(lead + " "):
                out.setdefault(tool, cmd)
                break
    return list(out.items())


class LintMiner:
    """Lint and formatter configurations → ``convention`` entries with the check that runs
    them; and, for a tool no configuration names, the command a guidance file tells a
    contributor to run."""

    name = "lint"
    version = "1"
    kinds: tuple[str, ...] = (KIND_CONVENTION,)
    reads = (
        "lint and formatter configurations (pyproject.toml tables, ruff.toml, .eslintrc*, "
        ".prettierrc*, .golangci.yml, go.mod, rustfmt.toml, pom.xml plugins, "
        ".pre-commit-config.yaml …) and, as data only, the commands CLAUDE.md, AGENTS.md "
        "and CONTRIBUTING name"
    )

    def mine(self, source: MineSource) -> Iterator[Finding]:
        found = detect_tools(source)
        for tool, path in found.items():
            t = _TOOLS[tool]
            runs = (
                f"crb's belt 5 ({CHECK_LINT}) runs it on a change when it finds this "
                "configuration and the tool is installed."
                if t.belt5
                else "crb does not run it, so it is advisory until a finish-gate command names it."
            )
            where = (
                f"The repository is a Go module ({path}), and gofmt is the formatter every Go "
                "toolchain ships"
                if tool == "gofmt"
                else f"The repository configures {tool} as its {t.role} in {path}"
            )
            yield Draft(
                kind=KIND_CONVENTION,
                slug=slugify(tool),
                title=fit(f"Code passes {tool}", TITLE_MAX),
                statement=fit(f"{where}: `{t.command}` accepts every changed file. {runs}"),
                path=path,
                characteristic=MAINTAINABILITY,
                check=CHECK_LINT if t.belt5 else "",
            )
        documented: set[str] = set()
        for path in GUIDANCE_FILES:
            if not source.has(path):
                continue
            text = source.text(path)
            if text is None:
                continue
            for tool, command in guidance_commands(text):
                if tool in found or tool in documented:
                    continue
                documented.add(tool)
                t = _TOOLS[tool]
                yield Draft(
                    kind=KIND_CONVENTION,
                    slug=slugify(f"documented-{tool}"),
                    title=fit(f"{path} asks for {tool}", TITLE_MAX),
                    statement=fit(
                        f"{path} tells a contributor to run `{command}` ({t.role}); the "
                        f"repository has no configuration file for {tool}. Advisory: crb does "
                        "not run it."
                    ),
                    path=path,
                    characteristic=MAINTAINABILITY,
                )


# ---------------------------------------------------------------------------
# Miner 4: the test layout and example tests → a test standard per language
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TestLayout:
    language: str
    pattern: re.Pattern[str]
    named: str
    configs: tuple[tuple[str, str], ...]  # (file, runner) in the order one is cited
    default_runner: str


_LAYOUTS: tuple[_TestLayout, ...] = (
    _TestLayout(
        "python",
        re.compile(r"(^|/)(test_[^/]+|[^/]+_test)\.py$"),
        "test_*.py",
        (("pytest.ini", "pytest"), ("conftest.py", "pytest"), ("pyproject.toml", "pytest"),
         ("setup.cfg", "pytest"), ("tox.ini", "tox")),
        "the Python test runner",
    ),
    _TestLayout("go", re.compile(r"_test\.go$"), "*_test.go", (("go.mod", "go test"),), "go test"),
    _TestLayout(
        "javascript",
        re.compile(r"(\.(test|spec)\.(m?[jt]sx?|cjs)$)|(^|/)__tests__/.+\.(m?[jt]sx?|cjs)$"),
        "*.test.ts or *.spec.js",
        (("package.json", "the package's test script"),),
        "the package's test script",
    ),
    _TestLayout(
        "jvm",
        re.compile(r"(^|/)src/test/(java|kotlin)/.+\.(java|kt)$"),
        "src/test/java/**/*Test.java",
        (("pom.xml", "mvn test"), ("build.gradle", "gradle test"),
         ("build.gradle.kts", "gradle test")),
        "the build's test task",
    ),
    _TestLayout(
        "rust", re.compile(r"(^|/)tests/[^/]+\.rs$"), "tests/*.rs",
        (("Cargo.toml", "cargo test"),), "cargo test",
    ),
    _TestLayout(
        "ruby", re.compile(r"(_spec|_test)\.rb$"), "*_spec.rb or *_test.rb",
        (("Gemfile", "bundle exec rake test"),), "the Ruby test runner",
    ),
)  # fmt: skip
_JS_RUNNERS = ("vitest", "jest", "mocha", "ava")


def _test_dir(path: str) -> str:
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "."


class TestLayoutMiner:
    """The test layout and example tests → a ``standard`` per language: a change leads to a
    failing test, where the repository keeps its tests, how it names and runs them, with
    example tests; scoped to the work types whose mined commits changed such tests."""

    __test__ = False  # not a pytest class, whatever its name
    name = "tests"
    version = "1"
    kinds: tuple[str, ...] = (KIND_STANDARD,)
    reads = (
        "the test files at the commit (the first example is cited), the runner's "
        "configuration and the tests the mined commits changed"
    )

    def mine(self, source: MineSource) -> Iterator[Finding]:
        for layout in _LAYOUTS:
            tests = [f for f in source.files if layout.pattern.search(f)]
            if not tests:
                continue
            dirs = Counter(_test_dir(f) for f in tests)
            top, _n = min(dirs.items(), key=lambda kv: (-kv[1], kv[0]))
            examples = sorted(f for f in tests if _test_dir(f) == top)[:3]
            runner, cited = layout.default_runner, ""
            for cfg, cfg_runner in layout.configs:
                if not source.has(cfg):
                    continue
                if cfg == "pyproject.toml" and not _has_table(
                    source.text(cfg), "tool.pytest.ini_options", "tool.pytest"
                ):
                    continue
                if cfg == "setup.cfg" and not _has_table(source.text(cfg), "tool:pytest"):
                    continue
                cited, runner = cfg, cfg_runner
                break
            if layout.language == "javascript" and cited:
                pkg = source.text(cited) or ""
                runner = next((r for r in _JS_RUNNERS if f'"{r}"' in pkg), runner)
            per = f" (per {cited})" if cited else ""
            classes = Counter(
                t.capability_class
                for t in source.tasks
                if t.capability_class in CLASS_DEFINITIONS
                and any(layout.pattern.search(f) for f in t.test_files)
            )
            scope = tuple(c for c, _ in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0])))
            where = f"{top}/" if top != "." else "the repository's root"
            shown = ", ".join(f"`{e}`" for e in examples)
            yield Draft(
                kind=KIND_STANDARD,
                slug=slugify(f"tests-{layout.language}"),
                title=fit(f"A {layout.language} change leads to a failing test", TITLE_MAX),
                statement=fit(
                    f"A {layout.language} change leads to a failing test that the change turns "
                    f"green. The repository keeps most of its {layout.language} tests under "
                    f"{where}, named like {layout.named}, run by {runner}{per}. "
                    f"Examples: {shown}."
                ),
                path=examples[0],
                work_types=scope[:32],
                characteristic=FUNCTIONAL_SUITABILITY,
                check=CHECK_TARGET,
            )


# ---------------------------------------------------------------------------
# Miner 5: the change profile → work-type candidates with counts
# ---------------------------------------------------------------------------

#: A kind of change recurs: one commit is an instance, two are the least that are a kind.
MIN_CANDIDATE_COMMITS = 2
_SIZES = ("XS", "S", "M", "L", "XL")


class ChangeProfileMiner:
    """The change profile → ``work-type`` candidates: each global class split by the part of
    the system its mined commits change, with the counts of mined commits, graded rows and
    clean ones. A candidate cites the graded rows it was learned from; one with none is
    noted with its counts and not proposed — replay its commits first."""

    name = "change-profile"
    version = "1"
    kinds: tuple[str, ...] = (KIND_WORK_TYPE,)
    reads = "the mined commits (class, size, files changed) and the graded rows of the ledger"

    def mine(self, source: MineSource) -> Iterator[Finding]:
        roots = source.component_roots
        rows_by_task: dict[str, list[GradedRow]] = {}
        for r in source.graded:
            rows_by_task.setdefault(r.task_id, []).append(r)
        groups: dict[tuple[str, str], list[MinedTask]] = {}
        for t in source.tasks:
            if t.capability_class not in CLASS_DEFINITIONS:
                continue
            parts = Counter(c for c in (component_of(f, roots) for f in t.src_files) if c)
            if not parts:
                continue
            part = min(parts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            groups.setdefault((t.capability_class, part), []).append(t)
        for (cls, part), tasks in sorted(groups.items()):
            if len(tasks) < MIN_CANDIDATE_COMMITS:
                continue
            rows = sorted({r.row_hash for t in tasks for r in rows_by_task.get(t.task_id, [])})
            clean = sum(1 for t in tasks for r in rows_by_task.get(t.task_id, []) if r.clean)
            sizes = Counter(t.size for t in tasks)
            counts = {"commits": len(tasks), "graded_rows": len(rows), "clean_rows": clean}
            counts.update({f"size_{s}": sizes[s] for s in _SIZES if sizes.get(s)})
            slug = slugify(f"{cls.replace('.', '-')}-in-{part.replace('/', '-')}")
            if not rows:
                yield Note(
                    f"work-type/{slug}",
                    "no graded rows to cite: replay these commits, then mine again",
                    counts,
                )
                continue
            by_size = ", ".join(f"{s} {sizes[s]}" for s in _SIZES if sizes.get(s))
            yield Draft(
                kind=KIND_WORK_TYPE,
                slug=slug,
                title=fit(f"{cls} in {part}", TITLE_MAX),
                statement=fit(
                    f"A candidate from the change profile: {len(tasks)} mined commits of "
                    f"{cls} change {part}/ (sizes {by_size}); {len(rows)} graded "
                    f"row{'s' if len(rows) != 1 else ''}, {clean} clean. A person names what "
                    "makes it a kind of change of its own before it is signed."
                ),
                rows=tuple(rows),
                parent_class=cls,
                examples=tuple(t.task_id for t in tasks[:10]),
            )


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """What a run did with one draft or note."""

    miner: str
    subject: str
    outcome: str
    reason: str = ""
    version: str = ""
    counts: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "miner": self.miner,
            "subject": self.subject,
            "outcome": self.outcome,
            "reason": self.reason,
            "version": self.version,
            "counts": dict(self.counts),
        }


@dataclass(frozen=True)
class Proposal:
    """An entry a run proposes, with the miner that mined it and the model that drafted its
    statement (``""`` when none did)."""

    entry: LibraryEntry
    miner: str
    drafted_by: str = ""


@dataclass(frozen=True)
class MineRun:
    """One run: the repository, the pinned commit, the miners applied (``name@version``),
    the proposals to append, and an outcome for every draft and note."""

    repo: str
    commit: str
    miners: tuple[str, ...]
    proposals: tuple[Proposal, ...]
    outcomes: tuple[Outcome, ...]
    files_read: tuple[str, ...] = ()

    def counts(self) -> dict[str, int]:
        c = Counter(o.outcome for o in self.outcomes)
        return {k: c.get(k, 0) for k in OUTCOMES}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MINERS_SCHEMA,
            "repo": self.repo,
            "commit": self.commit,
            "miners": list(self.miners),
            "counts": self.counts(),
            "proposals": [
                {
                    "entry_id": p.entry.entry_id,
                    "version": p.entry.version,
                    "miner": p.miner,
                    "drafted_by": p.drafted_by,
                    "entry": p.entry.content(),
                }
                for p in self.proposals
            ],
            "outcomes": [o.to_dict() for o in self.outcomes],
            "files_read": list(self.files_read),
        }


def _source_of(e: LibraryEntry) -> tuple[str, str, str, tuple[str, ...]]:
    p = e.provenance
    return (p.kind, p.path, p.digest, tuple(p.rows))


def standing(new: LibraryEntry, state: EntryState | None) -> tuple[str, str]:
    """``(outcome, reason)`` for a mined entry against the entry's standing state: the
    idempotency rule of the module docstring."""
    if state is None:
        return OUTCOME_PROPOSED, ""
    old = state.entry
    if is_person(old.proposed_by):
        return OUTCOME_HELD, "a person wrote this entry; a miner never replaces it"
    if state.status in FINAL_STATUSES:
        return OUTCOME_HELD, f"a person {state.status} this entry; only a person proposes it again"
    if _source_of(old) == _source_of(new):
        return OUTCOME_UNCHANGED, "its source is unchanged since it was proposed"
    return OUTCOME_PROPOSED, ""


def _entry_of(source: MineSource, miner: Miner, d: Draft) -> LibraryEntry:
    if d.kind not in miner.kinds:
        raise ValueError(f"the miner declared {miner.kinds}, not {d.kind}")
    if bool(d.path) == bool(d.rows):
        raise ValueError("a mined proposal cites one source: a file at the commit or graded rows")
    if d.path:
        digest = source.digest(d.path)
        if digest is None:
            raise ValueError(f"{d.path} is not a file of the repository at the commit")
        prov = Provenance(kind=PROVENANCE_FILE, path=d.path, commit=source.commit, digest=digest)
    else:
        known = {r.row_hash for r in source.graded}
        if not all(_HASH_RE.match(r) and r in known for r in d.rows):
            raise ValueError("a mined proposal cites only graded rows of this repository")
        prov = Provenance(kind=PROVENANCE_ROWS, rows=tuple(d.rows))
    return LibraryEntry(
        repo=source.repo,
        kind=d.kind,
        slug=d.slug,
        title=d.title,
        statement=d.statement,
        provenance=prov,
        proposed_by=proposer_of(miner),
        components=d.components,
        work_types=d.work_types,
        characteristic=d.characteristic,
        check=d.check,
        parent_class=d.parent_class,
        examples=d.examples,
        slots=d.slots,
    )


def _drafted(entry: LibraryEntry, draft: Draft, drafter: Drafter) -> LibraryEntry:
    if not _MODEL_RE.match(drafter.name):
        raise ValueError(f"a drafter names its model: {drafter.name!r}")
    statement = str(drafter.draft(draft))
    return LibraryEntry.from_dict(
        {
            **entry.content(),
            "statement": statement,
            "proposed_by": f"{PROPOSER_DRAFTED}{drafter.name}",
        }
    )


def run_miners(
    source: MineSource,
    *,
    names: Sequence[str] | None = None,
    states: Mapping[str, EntryState] | None = None,
    drafter: Drafter | None = None,
) -> MineRun:
    """Apply the registered miners (``names``, in registry order, or all of them) to
    ``source``; hold every draft to the contract and the record's rules; compare each with
    its entry's standing state (``states``: the repository's library as it stands); and
    return the run — the proposals for the caller to append, and an outcome for every draft
    and note. Nothing is written here."""
    chosen = [get_miner(n) for n in names] if names else [get_miner(n) for n in miner_names()]
    order = {n: i for i, n in enumerate(miner_names())}
    chosen.sort(key=lambda m: order[m.name])
    states = states or {}
    proposals: list[Proposal] = []
    outcomes: list[Outcome] = []
    taken: set[str] = set()
    for miner in chosen:
        who = f"{miner.name}@{miner.version}"
        try:
            # a using team's miner may yield anything: each finding is checked at run time
            findings: list[object] = list(miner.mine(source))
        except Exception as exc:  # one miner's fault never stops the others
            outcomes.append(Outcome(who, miner.name, OUTCOME_FAILED, redact(str(exc))[:300]))
            continue
        for f in findings:
            if isinstance(f, Note):
                outcomes.append(Outcome(who, f.subject, OUTCOME_NOTED, f.reason, "", f.counts))
                continue
            if not isinstance(f, Draft):
                outcomes.append(Outcome(who, repr(f)[:80], OUTCOME_REFUSED, "not a draft"))
                continue
            try:
                entry = _entry_of(source, miner, f)
            except ValueError as exc:
                outcomes.append(Outcome(who, f.entry_id, OUTCOME_REFUSED, redact(str(exc))))
                continue
            if entry.entry_id in taken:
                outcomes.append(
                    Outcome(who, entry.entry_id, OUTCOME_REFUSED, "another miner proposed it first")
                )
                continue
            taken.add(entry.entry_id)
            outcome, reason = standing(entry, states.get(entry.entry_id))
            drafted_by = ""
            if outcome == OUTCOME_PROPOSED and drafter is not None:
                try:
                    entry = _drafted(entry, f, drafter)
                    drafted_by = drafter.name
                except Exception as exc:  # a failed draft keeps the mined words
                    reason = f"the drafter failed, so the miner's words stand: {redact(str(exc))}"
            outcomes.append(Outcome(who, entry.entry_id, outcome, reason, entry.version))
            if outcome == OUTCOME_PROPOSED:
                proposals.append(Proposal(entry, who, drafted_by))
    return MineRun(
        repo=source.repo,
        commit=source.commit,
        miners=tuple(f"{m.name}@{m.version}" for m in chosen),
        proposals=tuple(proposals),
        outcomes=tuple(outcomes),
        files_read=source.files_read,
    )


#: The miners the product ships, in the order a run applies them.
SHIPPED: tuple[Miner, ...] = (
    AdrMiner(),
    OwnersMiner(),
    LintMiner(),
    TestLayoutMiner(),
    ChangeProfileMiner(),
)
for _m in SHIPPED:
    register_miner(_m)
del _m

__all__ = [
    "CHECK_LINT",
    "CHECK_TARGET",
    "GUIDANCE_FILES",
    "MAX_FILE_BYTES",
    "MINERS_SCHEMA",
    "MIN_CANDIDATE_COMMITS",
    "OUTCOMES",
    "OUTCOME_FAILED",
    "OUTCOME_HELD",
    "OUTCOME_NOTED",
    "OUTCOME_PROPOSED",
    "OUTCOME_REFUSED",
    "OUTCOME_UNCHANGED",
    "SHIPPED",
    "AdrMiner",
    "ChangeProfileMiner",
    "Draft",
    "Drafter",
    "Finding",
    "GradedRow",
    "LintMiner",
    "MineRun",
    "MineSource",
    "MinedTask",
    "Miner",
    "Note",
    "Outcome",
    "OwnersMiner",
    "Proposal",
    "TestLayoutMiner",
    "component_of",
    "component_roots",
    "describe_miners",
    "detect_tools",
    "fit",
    "get_miner",
    "guidance_commands",
    "list_files",
    "miner_names",
    "parse_codeowners",
    "proposer_of",
    "register_miner",
    "run_miners",
    "slugify",
    "source_from_git",
    "standing",
    "unregister_miner",
]
