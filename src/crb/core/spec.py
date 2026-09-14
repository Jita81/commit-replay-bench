"""The shared vocabulary: languages, size tiers, change classes, repo config, task spec.

Everything here is a frozen dataclass or a pure function. Nothing touches git
or the filesystem — that is :mod:`crb.core.git` / :mod:`crb.core.workspace`.

Design rules
------------
* **One size table.** The census, the factorial grader and the model bench each
  carried their own churn→tier boundaries. There is exactly one now
  (:data:`SIZE_TIERS`); it is the census table (the largest measured corpus) and
  it is stamped by :data:`crb.core.version.APPARATUS_VERSION`.
* **Two class axes, one resolved class.** :func:`classify_path` is the deterministic
  path taxonomy (path role + extension; most-specific wins; no LLM); a commit's
  *path class* is the class of its *source* files (:func:`classify_commit`). It is
  blind to intent — on a library repository every code change is ``bug.fix`` — so a
  task may also carry an :class:`~crb.core.classify.IntentLabel` (a model's or a
  human's judgement, made without the diff body). ``TaskSpec.capability_class`` is
  the **resolved** class (:func:`~crb.core.classify.resolve`: human > confident
  intent > path) and is what every cell key, ledger row and capability map keys
  on. The vocabulary is closed and lives in :mod:`crb.core.taxonomy`.
* **Repo config is data.** :class:`RepoConfig` says how to tell source from test,
  which runner to use, and what the regression belt covers. It round-trips to JSON
  and can load the census ``configs.json`` shape unchanged.
"""

from __future__ import annotations

import enum
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from crb.core.classify import IntentLabel, resolve
from crb.core.lint import plan_from_config
from crb.core.taxonomy import ALL_CLASSES, CLASS_VOCABULARY, INTENT_CLASSES, UNCLASSIFIED

# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------


class Language(enum.StrEnum):
    PYTHON = "python"
    GO = "go"
    JAVASCRIPT = "javascript"
    JVM = "jvm"
    RUST = "rust"

    @classmethod
    def parse(cls, value: str) -> Language:
        """Accept both the canonical names and the census short codes."""
        aliases = {
            "py": cls.PYTHON,
            "python": cls.PYTHON,
            "go": cls.GO,
            "golang": cls.GO,
            "js": cls.JAVASCRIPT,
            "javascript": cls.JAVASCRIPT,
            "typescript": cls.JAVASCRIPT,
            "ts": cls.JAVASCRIPT,
            "jvm": cls.JVM,
            "java": cls.JVM,
            "kotlin": cls.JVM,
            "rust": cls.RUST,
            "rs": cls.RUST,
        }
        try:
            return aliases[value.strip().lower()]
        except KeyError as e:
            raise ValueError(f"unknown language {value!r}") from e


# ---------------------------------------------------------------------------
# Size tiers (ONE table)
# ---------------------------------------------------------------------------

#: ``(upper_exclusive_churn, tier)`` — churn is added+deleted source lines.
SIZE_TIERS: tuple[tuple[int, str], ...] = (
    (10, "XS"),
    (40, "S"),
    (120, "M"),
    (400, "L"),
)
SIZE_TIER_NAMES: tuple[str, ...] = ("XS", "S", "M", "L", "XL")


def size_tier(src_churn: int) -> str:
    """Map source churn (added + deleted lines) to a size tier."""
    if src_churn < 0:
        raise ValueError("churn cannot be negative")
    for upper, tier in SIZE_TIERS:
        if src_churn < upper:
            return tier
    return "XL"


# ---------------------------------------------------------------------------
# Change classes (language-agnostic, deterministic)
# ---------------------------------------------------------------------------

# ``UNCLASSIFIED``, ``ALL_CLASSES`` (the path taxonomy), ``INTENT_CLASSES`` and the closed
# ``CLASS_VOCABULARY`` are defined once in :mod:`crb.core.taxonomy` and re-exported here.

_CODE_EXTS = frozenset(
    {
        ".py",
        ".cs",
        ".js",
        ".ts",
        ".mjs",
        ".cjs",
        ".go",
        ".java",
        ".rb",
        ".rs",
        ".php",
        ".kt",
        ".scala",
        ".swift",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".m",
        ".mm",
        ".fs",
    }
)
_FRONTEND_EXTS = frozenset({".tsx", ".jsx", ".vue", ".svelte", ".razor", ".cshtml"})
_DOC_EXTS = frozenset({".md", ".rst", ".txt", ".mdx", ".adoc"})

_TEST_NAME_RE = re.compile(r"(^|[./_-])tests?([./_-]|$)")


def _has(haystack: str, *needles: str) -> bool:
    return any(n in haystack for n in needles)


def _ext_of(name: str) -> str:
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def is_test_path(rel: str) -> bool:
    """Language-agnostic 'does this path look like a test file' heuristic.

    Used for the generic classifier and as a *fallback* when a repo has no
    explicit source/test layout configured. Repo-level decisions should go
    through :meth:`RepoConfig.is_test`, which is exact for the configured layout.
    """
    pl = "/" + rel.lower()
    name = pl.rsplit("/", 1)[-1]
    ext = _ext_of(name)
    looks_like_test = (
        _has(pl, "/test/", "/tests/", "/__tests__/", ".tests/", "/spec/")
        or _TEST_NAME_RE.search(name) is not None
        or ".spec." in name
        or name.endswith(
            ("test.cs", "tests.cs", "_test.py", "_test.go", ".test.ts", ".test.tsx", ".test.js")
        )
    )
    return looks_like_test and (ext in _CODE_EXTS or ext in _FRONTEND_EXTS)


def classify_path(rel: str) -> str:
    """Return the single best change class for a repo-relative path.

    Ordered specific → general; first match wins. Returns :data:`UNCLASSIFIED`
    for files outside the taxonomy (binaries, lockfiles, project metadata).
    """
    pl = "/" + rel.lower()
    name = pl.rsplit("/", 1)[-1]
    ext = _ext_of(name)

    if _has(
        pl, ".github/workflows/", ".gitlab-ci", "azure-pipelines", ".circleci/", ".buildkite/"
    ) or name in {
        "azure-pipelines.yml",
        "azure-pipelines.yaml",
        ".travis.yml",
        "jenkinsfile",
    }:
        return "ci.workflow.edit"
    if ext in {".tf", ".tfvars"} or pl.endswith(".tf.json"):
        return "infra.terraform.edit"
    if (
        _has(pl, "/charts/", "/helm/")
        or name in {"chart.yaml", "values.yaml"}
        or (_has(pl, "/templates/") and ext in {".yaml", ".yml"} and _has(pl, "chart", "helm"))
    ):
        return "infra.helm.edit"
    if ext in _DOC_EXTS:
        return "docs.update"
    if is_test_path(rel):
        return "test.add"
    if ext in _FRONTEND_EXTS:
        if _has(pl, "/pages/", "/routes/", "/views/", "/app/"):
            return "frontend.route.add"
        return "frontend.component.add"
    is_db_migration = (
        _has(pl, "/migrations/versions/", "/alembic/", "/db/migrate/", "/migrate/versions/")
        or (_has(pl, "/migrations/") and ext in {".py", ".sql", ".rb", ".cs"})
        or re.match(r"\d{12,14}[._-]", name) is not None
        or re.match(r"v\d+__", name) is not None
        or (ext == ".sql" and _has(pl, "migrat", "schema"))
    )
    if is_db_migration and (ext in _CODE_EXTS or ext == ".sql"):
        return "backend.migration.add"
    if (
        _has(pl, "/models/", "/entities/", "/domain/")
        or name.endswith(("model" + ext, "entity" + ext, "models" + ext))
    ) and ext in _CODE_EXTS:
        return "backend.model.edit"
    if (
        _has(pl, "/controllers/", "/routes/", "/api/", "/endpoints/", "/handlers/")
        or name.endswith(
            ("controller" + ext, "router" + ext, "routes" + ext, "endpoint" + ext, "api" + ext)
        )
    ) and ext in _CODE_EXTS:
        return "backend.route.add"
    if ext in _CODE_EXTS:
        return "bug.fix"
    return UNCLASSIFIED


def classify_commit(src_files: Sequence[str]) -> str:
    """Class of a commit = the most common class among its SOURCE files.

    Ties resolve to the first occurrence in ``src_files`` (deterministic).
    Empty input → :data:`UNCLASSIFIED`.
    """
    if not src_files:
        return UNCLASSIFIED
    counts = Counter(classify_path(p) for p in src_files)
    best = max(counts.values())
    for p in src_files:
        if counts[classify_path(p)] == best:
            return classify_path(p)
    return UNCLASSIFIED  # pragma: no cover — unreachable


# ---------------------------------------------------------------------------
# Repo config
# ---------------------------------------------------------------------------

BELT_TARGET_ONLY = "TARGET_ONLY"
BELT_AFFECTED_DIRS = "AFFECTED_DIRS"
BELT_BARE = "BARE"

#: Runner names. Each maps to a class in :mod:`crb.core.runners`.
RUNNERS: tuple[str, ...] = ("pytest", "go", "node", "vitest", "jest", "mocha", "maven", "cargo")

_DEFAULT_RUNNER_FOR_LANGUAGE: dict[Language, str] = {
    Language.PYTHON: "pytest",
    Language.GO: "go",
    Language.JAVASCRIPT: "mocha",
    Language.JVM: "maven",
    Language.RUST: "cargo",
}


@dataclass(frozen=True)
class RepoConfig:
    """How to replay commits in one repository.

    Attributes
    ----------
    name:
        Short identifier (ledger key). Lowercase, no spaces.
    language:
        Primary language; selects default runner and source/test heuristics.
    runner:
        One of :data:`RUNNERS`.
    src_prefix / test_prefix / ext:
        Layout: a file is *source* if it has ``ext`` and starts with ``src_prefix``
        (or, if ``src_prefix`` is empty, does NOT start with ``test_prefix``); a file
        is a *test* if it has ``ext`` and starts with ``test_prefix``. Go and Rust and
        ``test_mode="suffix"`` layouts override this (see :meth:`is_test`).
    test_mode / test_suffix:
        ``"prefix"`` (default) or ``"suffix"`` (e.g. Django-style ``*_tests.py``).
    belt_scope:
        Regression-belt scope: ``TARGET_ONLY`` (only the target tests),
        ``AFFECTED_DIRS`` (every test in the target tests' directories), ``BARE``
        (the runner's default discovery), or an explicit list of runner scopes.
    probe:
        A known-green test scope used by ``crb repo probe`` to prove the toolchain.
    runner_opts:
        Runner-specific options (``python``, ``pythonpath_suffix``, ``maven_flags``,
        ``mocha_require``, ``node_modules``…). Free-form but validated by the runner.
    lint:
        Belt 5 (``repo_lint_clean``): the repository's own formatter/linter, run on
        the changed non-test files at grade time. Empty (the default) ⇒ the runner
        auto-detects it from the repository's configuration (``gofmt``, ``ruff``,
        ``eslint``/``prettier``/``standard``, ``spotless``/``checkstyle``,
        ``cargo fmt``/``clippy`` — ADR-0011); ``{"command": [...], "paths":
        "changed"|"all", "timeout": s}`` declares it; ``{"disabled": true}`` switches
        the belt off for the repo (not evaluated, never a pass). Validated by
        :func:`crb.core.lint.plan_from_config`.
    path:
        Local clone path (host). Optional in the config; the CLI and server fill it.
    sandbox_image:
        Container image for the sandboxed executor (toolchain + deps).
    mining:
        ``log_n``, ``max_candidates``, ``target_valid``, ``hard_target`` — how far to
        walk history and how many tasks to keep per pool.
    """

    name: str
    language: Language
    runner: str = ""
    path: str = ""
    src_prefix: str = ""
    test_prefix: str = ""
    ext: str = ""
    test_mode: str = "prefix"
    test_suffix: str = ""
    belt_scope: str | tuple[str, ...] = BELT_TARGET_ONLY
    probe: str = ""
    url: str = ""
    layer: str = ""
    runner_opts: Mapping[str, Any] = field(default_factory=dict)
    sandbox_image: str = ""
    mining: Mapping[str, int] = field(default_factory=dict)
    lint: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", self.name):
            raise ValueError(f"repo name {self.name!r} must be lowercase [a-z0-9._-], ≤64 chars")
        if not self.runner:
            object.__setattr__(self, "runner", _DEFAULT_RUNNER_FOR_LANGUAGE[self.language])
        if self.runner not in RUNNERS:
            raise ValueError(f"unknown runner {self.runner!r}; expected one of {RUNNERS}")
        if self.test_mode not in {"prefix", "suffix"}:
            raise ValueError("test_mode must be 'prefix' or 'suffix'")
        if self.test_mode == "suffix" and not self.test_suffix:
            raise ValueError("test_mode='suffix' requires test_suffix")
        if not self.ext:
            object.__setattr__(self, "ext", _DEFAULT_EXT[self.language])
        if not isinstance(self.belt_scope, str):
            object.__setattr__(self, "belt_scope", tuple(self.belt_scope))
        if isinstance(self.belt_scope, str) and self.belt_scope not in {
            BELT_TARGET_ONLY,
            BELT_AFFECTED_DIRS,
            BELT_BARE,
        }:
            raise ValueError(
                f"belt_scope {self.belt_scope!r} must be TARGET_ONLY | AFFECTED_DIRS | BARE | [scopes]"
            )
        object.__setattr__(self, "runner_opts", dict(self.runner_opts))
        object.__setattr__(self, "mining", dict(self.mining))
        object.__setattr__(self, "lint", dict(self.lint))
        plan_from_config(self.lint)  # validates the declared shape (raises ValueError)

    # --- source / test discrimination (exact for the configured layout) -------
    @property
    def exts(self) -> tuple[str, ...]:
        """``ext`` may list alternatives separated by ``|`` (e.g. ``.ts|.tsx``)."""
        return tuple(e for e in self.ext.split("|") if e)

    @property
    def test_suffixes(self) -> tuple[str, ...]:
        """``test_suffix`` may list alternatives separated by ``|``
        (e.g. ``.unit.test.mjs|.jsdom.test.mjs``)."""
        return tuple(x for x in self.test_suffix.split("|") if x)

    def has_ext(self, rel: str) -> bool:
        return rel.endswith(self.exts)

    def has_test_suffix(self, rel: str) -> bool:
        return bool(self.test_suffixes) and rel.endswith(self.test_suffixes)

    def is_test(self, rel: str) -> bool:
        if self.test_mode == "suffix":
            return self.has_test_suffix(rel)
        if self.language is Language.RUST:
            return rel.startswith("tests/") and rel.endswith(".rs")
        if not self.has_ext(rel):
            return False
        if self.language is Language.GO:
            return rel.endswith("_test.go")
        if self.language is Language.JAVASCRIPT:
            tp = self.test_prefix
            return rel.startswith(tp) and not rel.startswith(tp + "support/")
        return bool(self.test_prefix) and rel.startswith(self.test_prefix)

    def is_src(self, rel: str) -> bool:
        if self.test_mode == "suffix":
            return (
                self.has_ext(rel)
                and not self.has_test_suffix(rel)
                and rel.startswith(self.src_prefix)
            )
        if self.language is Language.RUST:
            return rel.startswith("src/") and rel.endswith(".rs")
        if self.language is Language.JVM:
            # JVM changes span code + templates/properties under src/main/
            sp = self.src_prefix
            mod = sp[: sp.find("src/main/")] if "src/main/" in sp else ""
            return rel.startswith(mod + "src/main/")
        if not self.has_ext(rel):
            return False
        if self.language is Language.GO:
            return not rel.endswith("_test.go")
        if self.src_prefix:
            return rel.startswith(self.src_prefix)
        return not (self.test_prefix and rel.startswith(self.test_prefix))

    def language_files(self, files: Iterable[str]) -> list[str]:
        """Files that count toward the per-commit file cap (all files for JVM)."""
        files = list(files)
        if self.language is Language.JVM:
            return files
        return [f for f in files if self.has_ext(f)]

    # --- serialisation ----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["language"] = self.language.value
        d["belt_scope"] = (
            list(self.belt_scope) if isinstance(self.belt_scope, tuple) else self.belt_scope
        )
        return d

    @classmethod
    def from_dict(cls, name: str, d: Mapping[str, Any]) -> RepoConfig:
        """Load from the native shape OR the census ``configs.json`` shape."""
        lang = Language.parse(str(d.get("language") or d.get("lang") or ""))
        runner = str(d.get("runner") or "")
        if not runner and "js_tool" in d:
            runner = {"node": "node", "vitest": "vitest", "jest": "jest", "mocha": "mocha"}[
                d["js_tool"]
            ]
        opts: dict[str, Any] = dict(d.get("runner_opts") or {})
        for k in ("pythonpath_suffix", "maven_flags", "pip", "pip_fallback", "uninstall", "python"):
            if k in d and k not in opts:
                opts[k] = d[k]
        mining: dict[str, int] = dict(d.get("mining") or {})
        for k in ("log_n", "max_candidates", "target_valid", "hard_target"):
            if k in d and k not in mining:
                mining[k] = int(d[k])
        belt = d.get("belt_scope", BELT_TARGET_ONLY)
        if isinstance(belt, list):
            belt = tuple(str(b) for b in belt)
        return cls(
            name=name,
            language=lang,
            runner=runner,
            path=str(d.get("path", "")),
            src_prefix=str(d.get("src_prefix", "")),
            test_prefix=str(d.get("test_prefix", "")),
            ext=str(d.get("ext", "")),
            test_mode=str(d.get("test_mode", "prefix")),
            test_suffix=str(d.get("test_suffix", "")),
            belt_scope=belt,
            probe=str(d.get("probe", "")),
            url=str(d.get("url", "")),
            layer=str(d.get("layer", "")),
            runner_opts=opts,
            sandbox_image=str(d.get("sandbox_image", "")),
            mining=mining,
            lint=dict(d.get("lint") or {}),
        )


_DEFAULT_EXT: dict[Language, str] = {
    Language.PYTHON: ".py",
    Language.GO: ".go",
    Language.JAVASCRIPT: ".js",
    Language.JVM: ".java",
    Language.RUST: ".rs",
}


# ---------------------------------------------------------------------------
# Task spec
# ---------------------------------------------------------------------------

POOL_STANDARD = "standard"
POOL_HARD = "hard"


@dataclass(frozen=True)
class TaskSpec:
    """One replayable commit, fully resolved for grading.

    A task is *replayable* when, at the commit's parent with only the commit's
    test files overlaid, the target tests are RED (``red_checked``), and — once
    gold-checked — the commit's own source turns them GREEN with no new failures
    in the belt scope (``gold_clean``). Both are recorded, never assumed.

    Class axes: ``path_class`` is the class assigned without an intent label (the
    miner's :func:`classify_commit`; the backlog's declared class for a factory
    task); ``intent`` is an optional :class:`~crb.core.classify.IntentLabel`.
    ``capability_class`` is **derived** at construction —
    :func:`~crb.core.classify.resolve` (human > confident intent > path) — and is
    what every consumer keys on; passing it without ``path_class`` (the pre-label
    shape, and every stored task from before labels existed) makes it the path
    class. ``class_source`` says which axis won.
    """

    task_id: str  # the commit sha (full)
    repo: str
    subject: str
    authored: str  # ISO-8601 author date
    test_files: tuple[str, ...]
    src_files: tuple[str, ...]
    target_tests: tuple[str, ...]  # runner scope for the target (belt 2)
    belt_scope: tuple[str, ...]  # runner scope for the regression belt (belt 3); () = BARE
    pool: str = POOL_STANDARD
    src_churn: int = 0
    size: str = "XS"
    capability_class: str = UNCLASSIFIED
    language: str = ""
    baseline_failing: tuple[str, ...] = ()
    red_checked: bool = False
    gold_clean: bool | None = None
    gold_note: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)
    path_class: str = ""
    intent: IntentLabel | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{7,64}", self.task_id):
            raise ValueError(f"task_id must be a git sha, got {self.task_id!r}")
        if self.pool not in {POOL_STANDARD, POOL_HARD}:
            raise ValueError(f"pool must be {POOL_STANDARD!r} or {POOL_HARD!r}")
        if self.size not in SIZE_TIER_NAMES:
            raise ValueError(f"size {self.size!r} not in {SIZE_TIER_NAMES}")
        if not self.test_files:
            raise ValueError("a task needs at least one test file (the oracle)")
        if not self.src_files:
            raise ValueError("a task needs at least one source file")
        for attr in ("test_files", "src_files", "target_tests", "belt_scope", "baseline_failing"):
            object.__setattr__(self, attr, tuple(getattr(self, attr)))
        object.__setattr__(self, "labels", dict(self.labels))
        # Class axes → the resolved class (the invariant every consumer relies on).
        if not self.path_class:
            object.__setattr__(self, "path_class", self.capability_class or UNCLASSIFIED)
        object.__setattr__(
            self, "capability_class", resolve(self.path_class, self.intent).capability_class
        )

    @property
    def short_id(self) -> str:
        return self.task_id[:10]

    @property
    def class_source(self) -> str:
        """Which axis produced ``capability_class``: ``human`` | ``intent`` | ``path``."""
        return resolve(self.path_class, self.intent).source

    @property
    def class_reason(self) -> str:
        return resolve(self.path_class, self.intent).reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "repo": self.repo,
            "subject": self.subject,
            "authored": self.authored,
            "test_files": list(self.test_files),
            "src_files": list(self.src_files),
            "target_tests": list(self.target_tests),
            "belt_scope": list(self.belt_scope),
            "pool": self.pool,
            "src_churn": self.src_churn,
            "size": self.size,
            "capability_class": self.capability_class,
            "language": self.language,
            "baseline_failing": list(self.baseline_failing),
            "red_checked": self.red_checked,
            "gold_clean": self.gold_clean,
            "gold_note": self.gold_note,
            "labels": dict(self.labels),
            "path_class": self.path_class,
            "intent": self.intent.to_dict() if self.intent is not None else None,
            "class_source": self.class_source,  # derived; ignored on load
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> TaskSpec:
        """Load from the native shape OR a census ``<repo>_tasks.json`` record.

        Pre-label records carry ``capability_class`` only: it becomes ``path_class``
        and, with no intent, the resolved class — byte-for-byte the old verdict."""
        task_id = str(d.get("task_id") or d.get("task") or d.get("commit"))
        raw_intent = d.get("intent")
        intent: IntentLabel | None
        if isinstance(raw_intent, IntentLabel):
            intent = raw_intent
        elif isinstance(raw_intent, Mapping):
            intent = IntentLabel.from_dict(raw_intent)
        else:
            intent = None
        return cls(
            task_id=task_id,
            repo=str(d.get("repo", "")),
            subject=str(d.get("subject", "")),
            authored=str(d.get("authored", "")),
            test_files=tuple(d.get("test_files", ())),
            src_files=tuple(d.get("src_files", ())),
            target_tests=tuple(d.get("target_tests", ())),
            belt_scope=tuple(d.get("belt_scope", ())),
            pool=str(d.get("pool", POOL_STANDARD)),
            src_churn=int(d.get("src_churn", 0)),
            size=str(d.get("size") or size_tier(int(d.get("src_churn", 0)))),
            capability_class=str(
                d.get("capability_class") or classify_commit(list(d.get("src_files", ())))
            ),
            language=str(d.get("language", "")),
            baseline_failing=tuple(d.get("baseline_failing", ())),
            red_checked=bool(d.get("red_checked", "baseline_failing" in d)),
            gold_clean=d.get("gold_clean"),
            gold_note=str(d.get("gold_note", "")),
            labels=dict(d.get("labels") or {}),
            path_class=str(d.get("path_class") or ""),
            intent=intent,
        )

    def with_(self, **changes: Any) -> TaskSpec:
        """A copy with fields replaced. ``capability_class`` is derived, so changing
        it alone changes the *path* class (the only axis a caller sets directly);
        ``intent`` accepts an :class:`~crb.core.classify.IntentLabel`, a dict or
        ``None`` (clears the label)."""
        d = self.to_dict()
        if "capability_class" in changes and "path_class" not in changes:
            changes = {**changes, "path_class": changes["capability_class"]}
        d.update(changes)
        return TaskSpec.from_dict(d)


__all__ = [
    "ALL_CLASSES",
    "BELT_AFFECTED_DIRS",
    "BELT_BARE",
    "BELT_TARGET_ONLY",
    "CLASS_VOCABULARY",
    "INTENT_CLASSES",
    "POOL_HARD",
    "POOL_STANDARD",
    "RUNNERS",
    "SIZE_TIERS",
    "SIZE_TIER_NAMES",
    "UNCLASSIFIED",
    "IntentLabel",
    "Language",
    "RepoConfig",
    "TaskSpec",
    "classify_commit",
    "classify_path",
    "is_test_path",
    "size_tier",
]
