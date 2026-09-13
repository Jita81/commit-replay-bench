"""Importers for the evidence that predates crb v2, so the product boots with history.

Two legacy sources exist and they are **not** the same kind of evidence:

1. **The expansion-bench census (2026-07-08)** — 1,071 per-trial verdicts from the
   polyglot commit-replay grader (``bench.py``), each with its three or four
   belts recorded. These are genuine per-trial observations and import as
   :class:`~crb.core.ledger.GradeRow` under ``provenance="imported:…"`` with an
   *imported* evidence pack (the raw row, hashed) so "no pack ⇒ no Q1" still
   holds. Rows graded before belt 4 existed have no ``source_changed`` key and
   are stamped ``belt_set="v3-legacy"``; **a belt that was never measured is
   never invented** — it stays ``None`` and the row's invariant is checked over
   the belts it actually recorded.

2. **Athena's benchmark ledger** — ``BenchmarkRow`` records. These are
   *aggregates*: one row per ``(classification × model × harness)`` run carrying
   ``n_samples`` collapsed into a ``quality_mean``. They have no task id, no
   per-trial belts and no evidence pack, so there is nothing a ``GradeRow`` could
   truthfully say about any single trial. Fabricating ``n_samples`` per-trial rows
   from a mean would be inventing evidence, and the grade ledger's write-time
   invariants exist precisely to make that impossible. They import as
   :class:`AggregateRow` — a reference-only shape that never enters the grade
   ledger, never feeds :func:`~crb.core.ledger.cell_stats` and never routes.

Everything here is deterministic: the same input files produce byte-identical
rows (fixed import timestamp, content-derived ids), so a re-import is detectable
by evidence-pack hash rather than by wall clock.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.evidence import canonical_json, sha256_text
from crb.core.grade import MODE_BLIND, MODE_SIGHTED
from crb.core.ledger import (
    BELT_SET_V3_LEGACY,
    BELT_SET_V4,
    PROCESS_REPLAY,
    GradeRow,
)
from crb.core.runners import get_runner
from crb.core.spec import POOL_STANDARD, RepoConfig, TaskSpec

EventFn = Callable[[str, Mapping[str, Any]], None]

# ---------------------------------------------------------------------------
# Census constants — fixed, so an import is reproducible byte-for-byte
# ---------------------------------------------------------------------------

CENSUS_DATE = "2026-07-08"
CENSUS_SOURCE = f"expansion-bench-census-{CENSUS_DATE}"
CENSUS_PROVENANCE = f"imported:{CENSUS_SOURCE}"
#: The census was graded on the day it was banked; every imported row carries this
#: one timestamp (never ``now()``), so a re-import is byte-identical.
CENSUS_IMPORT_CREATED = f"{CENSUS_DATE}T00:00:00+00:00"
CENSUS_APPARATUS_VERSION = "1.0-census"
CENSUS_BUILDER = "claude-code-workflow"
CENSUS_DEFAULT_MODEL = "sonnet"
CENSUS_PROVIDER = "anthropic"
CENSUS_ACTOR = "import"

IMPORTED_EVIDENCE_SCHEMA = "crb.evidence.imported.v1"

BENCHMARK_LEDGER_PROVENANCE = "imported:athena-benchmark-ledger"
AGGREGATE_SCHEMA = "crb.aggregate.imported.v1"

#: Census task files are ``<repo>_tasks.json``; this one is a bank of task ids, not tasks.
_NOT_A_TASK_FILE = frozenset({"banked_tasks.json"})

_SIZE_CANON: dict[str, str] = {
    "xs": "XS",
    "extra-small": "XS",
    "s": "S",
    "small": "S",
    "thin": "S",
    "m": "M",
    "medium": "M",
    "med": "M",
    "l": "L",
    "large": "L",
    "thick": "L",
    "xl": "XL",
    "extra-large": "XL",
    "xxl": "XL",
}


class LegacyImportError(ValueError):
    """A legacy record cannot be mapped without inventing something."""


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def _read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Repo configs
# ---------------------------------------------------------------------------


def import_repo_configs(configs_json: str | Path) -> dict[str, RepoConfig]:
    """Load the census ``configs.json`` (``{name: {...}}``) into :class:`RepoConfig`\\ s.

    :meth:`RepoConfig.from_dict` already understands the census shape (``lang``,
    ``js_tool``, flat pip/maven keys); this just iterates and keys by name.
    """
    raw = _read_json(configs_json)
    if not isinstance(raw, Mapping):
        raise LegacyImportError(f"{configs_json}: expected an object of repo configs")
    out: dict[str, RepoConfig] = {}
    for name, d in raw.items():
        if not isinstance(d, Mapping):
            raise LegacyImportError(f"{configs_json}: config {name!r} is not an object")
        out[str(name)] = RepoConfig.from_dict(str(name), d)
    return out


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def _task_files(tasks_dir: str | Path) -> list[Path]:
    return sorted(
        p
        for p in Path(tasks_dir).glob("*_tasks.json")
        if p.is_file() and p.name not in _NOT_A_TASK_FILE
    )


def _census_task(repo: str, config: RepoConfig, rec: Mapping[str, Any]) -> TaskSpec:
    """One census task record → :class:`TaskSpec`.

    The census stored the regression-belt scope per *repo* (``configs.json``), not
    per task, so it is resolved here through the repo's runner exactly as the
    miner would resolve it today. Nothing else is derived: class comes from the
    recorded ``src_files`` (:func:`~crb.core.spec.classify_commit`), size from the
    recorded tier (or churn), gold from the recorded ``gold_clean``.
    """
    d: dict[str, Any] = dict(rec)
    d["repo"] = repo
    d["language"] = config.language.value
    if not d.get("pool"):
        d["pool"] = POOL_STANDARD
    if not d.get("size"):
        d.pop("size", None)  # let from_dict derive it from src_churn
    labels: dict[str, str] = dict(d.get("labels") or {})
    labels["provenance"] = CENSUS_PROVENANCE
    if rec.get("oracle_invalid"):
        labels["oracle_invalid"] = "true"
    d["labels"] = labels
    task = TaskSpec.from_dict(d)
    if not task.belt_scope and not rec.get("belt_scope"):
        runner = get_runner(config)
        task = task.with_(belt_scope=list(runner.belt_scope(task.target_tests, task.test_files)))
    return task


def import_census_tasks(
    tasks_dir: str | Path,
    configs_json: str | Path,
    *,
    on_event: EventFn | None = None,
) -> Iterator[TaskSpec]:
    """Yield every task in ``<tasks_dir>/<repo>_tasks.json`` as a :class:`TaskSpec`.

    A repo with no config in ``configs_json`` cannot be imported (its language and
    belt policy are unknown) and raises :class:`LegacyImportError` rather than
    guessing.
    """
    configs = import_repo_configs(configs_json)
    for path in _task_files(tasks_dir):
        repo = path.name[: -len("_tasks.json")]
        if repo not in configs:
            raise LegacyImportError(f"{path.name}: no config for repo {repo!r} in {configs_json}")
        raw = _read_json(path)
        if not isinstance(raw, Mapping):
            raise LegacyImportError(f"{path.name}: expected an object keyed by commit sha")
        n = 0
        for sha, rec in raw.items():
            if not isinstance(rec, Mapping):
                raise LegacyImportError(f"{path.name}: record {sha!r} is not an object")
            rec2 = dict(rec)
            rec2.setdefault("task", sha)
            yield _census_task(repo, configs[repo], rec2)
            n += 1
        _emit(on_event, "legacy.tasks", repo=repo, file=path.name, count=n)


def _task_index(tasks_dir: str | Path, configs_json: str | Path) -> dict[tuple[str, str], TaskSpec]:
    return {(t.repo, t.task_id): t for t in import_census_tasks(tasks_dir, configs_json)}


# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportedGrade:
    """A census verdict mapped to a ledger row, with the imported pack it hashes to.

    ``pack`` is what an auditor opens: the raw census row verbatim under an
    imported-evidence envelope. ``row.evidence_pack_hash`` is its canonical hash.
    """

    row: GradeRow
    pack: Mapping[str, Any]
    line: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "pack", dict(self.pack))

    @property
    def pack_hash(self) -> str:
        return self.row.evidence_pack_hash


def imported_pack(raw: Mapping[str, Any], *, source: Mapping[str, Any]) -> dict[str, Any]:
    """The imported-evidence envelope. Its canonical hash is the row's pack hash."""
    return {"schema": IMPORTED_EVIDENCE_SCHEMA, "source": dict(source), "row": dict(raw)}


def imported_pack_hash(pack: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json(pack))


def _belt(raw: Mapping[str, Any], name: str) -> bool | None:
    """A recorded belt is a bool; an absent belt is ``None`` — never defaulted."""
    v = raw.get(name)
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    raise LegacyImportError(f"belt {name}={v!r} is not a boolean")


def _census_grade(
    raw: Mapping[str, Any],
    *,
    line: int,
    task: TaskSpec,
    config: RepoConfig,
    source_file: str,
) -> ImportedGrade:
    for key in ("repo", "task", "clean"):
        if key not in raw:
            raise LegacyImportError(f"line {line}: census row has no {key!r}")
    source_changed = _belt(raw, "source_changed")
    belt_set = BELT_SET_V4 if "source_changed" in raw else BELT_SET_V3_LEGACY
    pack = imported_pack(
        raw, source={"provenance": CENSUS_SOURCE, "file": source_file, "line": line}
    )
    pack_hash = imported_pack_hash(pack)
    labels: dict[str, str] = {}
    if raw.get("operation"):
        labels["operation"] = str(raw["operation"])
    if raw.get("regraded_calm"):
        labels["regraded_calm"] = "true"
    new_failures = raw.get("new_failures") or ()
    row = GradeRow(
        repo=str(raw["repo"]),
        task_id=str(raw["task"]),
        clean=bool(raw["clean"]),
        tests_unmodified=_belt(raw, "tests_unmodified"),
        target_green=_belt(raw, "target_green"),
        no_new_failures=_belt(raw, "no_new_failures"),
        source_changed=source_changed,
        capability_class=task.capability_class,
        size=str(raw.get("size") or task.size),
        language=config.language.value,
        pool=str(raw.get("pool") or task.pool or POOL_STANDARD),
        mode=MODE_BLIND if raw.get("blind_mode") else MODE_SIGHTED,
        process_step=PROCESS_REPLAY,
        builder=CENSUS_BUILDER,
        model=str(raw.get("model") or CENSUS_DEFAULT_MODEL),
        provider=CENSUS_PROVIDER,
        run_id=str(raw.get("wave", "")),
        trial=str(raw.get("trial", "")),
        actor=CENSUS_ACTOR,
        created=CENSUS_IMPORT_CREATED,
        disqualified=bool(raw.get("disqualified", False)),
        dq_reason=str(raw.get("dq_reason", "")),
        error=str(raw.get("error", "")),
        new_failures_count=len(new_failures),
        gold_clean=task.gold_clean,
        evidence_pack_hash=pack_hash,
        apparatus_version=CENSUS_APPARATUS_VERSION,
        belt_set=belt_set,
        provenance=CENSUS_PROVENANCE,
        labels=labels,
        row_id=sha256_text(f"{CENSUS_PROVENANCE}:{pack_hash}")[:32],
    )
    return ImportedGrade(row=row, pack=pack, line=line)


def import_census(
    grades_jsonl: str | Path,
    tasks_dir: str | Path,
    configs_json: str | Path,
    *,
    on_event: EventFn | None = None,
) -> Iterator[ImportedGrade]:
    """Map every census verdict to a ledger row + imported pack.

    A verdict whose task is not in ``tasks_dir`` cannot be classified or sized
    honestly; it is **skipped** (``legacy.skip`` event), never yielded with
    guessed fields. Malformed rows raise :class:`LegacyImportError` — the census
    is a fixed, already-validated artefact, so a malformed row is a bug, not data.

    Exact-duplicate lines (the census appended three verdicts twice) are imported
    faithfully — each line is its own observation in the source — but the later
    copy is labelled ``duplicate_of_line`` so a reader can collapse them.
    """
    configs = import_repo_configs(configs_json)
    tasks = _task_index(tasks_dir, configs_json)
    path = Path(grades_jsonl)
    seen_raw: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            raw = json.loads(text)
            if not isinstance(raw, Mapping):
                raise LegacyImportError(f"line {line_no}: census row is not an object")
            key = (str(raw.get("repo", "")), str(raw.get("task", "")))
            task = tasks.get(key)
            config = configs.get(key[0])
            if task is None or config is None:
                _emit(
                    on_event,
                    "legacy.skip",
                    line=line_no,
                    repo=key[0],
                    task=key[1],
                    reason="no census task record" if config else "no repo config",
                )
                continue
            ig = _census_grade(raw, line=line_no, task=task, config=config, source_file=path.name)
            canon = canonical_json(raw)
            if canon in seen_raw:
                ig = ImportedGrade(
                    row=GradeRow.from_dict(
                        {
                            **ig.row.to_dict(),
                            "labels": {
                                **ig.row.labels,
                                "duplicate_of_line": str(seen_raw[canon]),
                            },
                        }
                    ),
                    pack=ig.pack,
                    line=ig.line,
                )
            else:
                seen_raw[canon] = line_no
            _emit(
                on_event,
                "legacy.grade",
                line=line_no,
                repo=ig.row.repo,
                task=ig.row.task_id,
                belt_set=ig.row.belt_set,
                clean=ig.row.clean,
            )
            yield ig


def import_census_grades(
    grades_jsonl: str | Path,
    tasks_dir: str | Path,
    configs_json: str | Path,
    *,
    on_event: EventFn | None = None,
) -> Iterator[GradeRow]:
    """Census verdicts as ledger rows (see :func:`import_census` for the pack)."""
    for ig in import_census(grades_jsonl, tasks_dir, configs_json, on_event=on_event):
        yield ig.row


# ---------------------------------------------------------------------------
# Athena benchmark ledger — AGGREGATE rows, reference only
# ---------------------------------------------------------------------------


def canonical_size(raw: Any) -> str:
    """Map a free-form size token to ``XS..XL``; ``""`` when absent or unknown."""
    if not isinstance(raw, str):
        return ""
    return _SIZE_CANON.get(raw.strip().lower(), "")


def _split_classification(value: Any) -> tuple[str, str]:
    """``"Size/Complexity/Type"`` → ``(size_tier, complexity_tier)``, ``""`` when unstamped."""
    if not isinstance(value, str) or "/" not in value:
        return ("", "")
    parts = value.split("/")
    return (canonical_size(parts[0]), canonical_size(parts[1]) if len(parts) > 1 else "")


def _opt_float(v: Any) -> float | None:
    return None if v is None else float(v)


def _opt_int(v: Any) -> int | None:
    return None if v is None else int(v)


@dataclass(frozen=True)
class AggregateRow:
    """One imported ``BenchmarkRow`` aggregate — a *reference view*, not a grade.

    Why this is not a :class:`~crb.core.ledger.GradeRow`
    -----------------------------------------------------
    A grade row is one trial with its belts and its evidence pack; the ledger
    refuses a clean row without both. A ``BenchmarkRow`` is ``n_samples`` trials
    collapsed to ``quality_mean`` (an oracle pass-rate under Athena's apparatus,
    not a four-belt verdict) with no task id, no per-trial belts and no pack.
    Expanding it into ``n_samples`` rows would require inventing which trials
    passed and under which belts — exactly the fabrication the write-time
    invariants exist to prevent. So these rows are kept beside the ledger for
    reference (what Athena measured, on which model, at what cost) and are never
    counted in cell statistics or routing.

    ``false_q1_total`` is carried verbatim: a config that recorded any false-Q1 is
    untrusted for that class in Athena's own terms (:attr:`trusted`).
    """

    created: str
    ground: str
    capability_class: str
    model: str
    harness: str
    n_samples: int
    quality_mean: float
    quality_stddev: float
    false_q1_total: int
    source_provenance: str
    provider: str = ""
    process_step: str = ""
    size: str = ""
    complexity: str = ""
    catalog_classification: str = ""
    earned_q1: int | None = None
    q1_band_count: int | None = None
    q3_band_count: int | None = None
    token_cost_usd_mean: float | None = None
    latency_s_mean: float | None = None
    human_verified: bool | None = None
    human_corrections: int | None = None
    raw_hash: str = ""
    provenance: str = BENCHMARK_LEDGER_PROVENANCE
    schema: str = AGGREGATE_SCHEMA
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", dict(self.labels))
        if self.n_samples < 0:
            raise LegacyImportError("n_samples cannot be negative")
        if not 0.0 <= self.quality_mean <= 1.0:
            raise LegacyImportError(f"quality_mean {self.quality_mean} outside [0, 1]")
        if self.false_q1_total < 0:
            raise LegacyImportError("false_q1_total cannot be negative")

    @property
    def trusted(self) -> bool:
        """Athena's own pre-filter: zero objective false-Q1 on this config × class."""
        return self.false_q1_total == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "provenance": self.provenance,
            "source_provenance": self.source_provenance,
            "created": self.created,
            "ground": self.ground,
            "capability_class": self.capability_class,
            "model": self.model,
            "harness": self.harness,
            "provider": self.provider,
            "process_step": self.process_step,
            "size": self.size,
            "complexity": self.complexity,
            "catalog_classification": self.catalog_classification,
            "n_samples": self.n_samples,
            "quality_mean": self.quality_mean,
            "quality_stddev": self.quality_stddev,
            "false_q1_total": self.false_q1_total,
            "trusted": self.trusted,
            "earned_q1": self.earned_q1,
            "q1_band_count": self.q1_band_count,
            "q3_band_count": self.q3_band_count,
            "token_cost_usd_mean": self.token_cost_usd_mean,
            "latency_s_mean": self.latency_s_mean,
            "human_verified": self.human_verified,
            "human_corrections": self.human_corrections,
            "raw_hash": self.raw_hash,
            "labels": dict(self.labels),
        }

    @classmethod
    def from_benchmark_row(cls, d: Mapping[str, Any]) -> AggregateRow:
        """Map one serialised Athena ``BenchmarkRow`` (see ``benchmark_ledger.py``)."""
        for key in ("created", "ground", "model"):
            if key not in d:
                raise LegacyImportError(f"benchmark row has no {key!r}")
        size, complexity = _split_classification(d.get("catalog_classification"))
        cc = d.get("catalog_classification")
        return cls(
            created=str(d["created"]),
            ground=str(d["ground"]),
            capability_class=str(d.get("capability_class") or ""),
            model=str(d["model"]),
            harness=str(d.get("harness") or ""),
            provider=str(d.get("provider") or ""),
            process_step=str(d.get("process_step") or ""),
            n_samples=int(d.get("n_samples") or 0),
            quality_mean=float(d.get("quality_mean") or 0.0),
            quality_stddev=float(d.get("quality_stddev") or 0.0),
            false_q1_total=int(d.get("false_q1_total") or 0),
            source_provenance=str(d.get("provenance") or ""),
            size=size,
            complexity=complexity,
            catalog_classification=cc if isinstance(cc, str) else "",
            earned_q1=_opt_int(d.get("earned_q1")),
            q1_band_count=_opt_int(d.get("q1_band_count")),
            q3_band_count=_opt_int(d.get("q3_band_count")),
            token_cost_usd_mean=_opt_float(d.get("token_cost_usd_mean")),
            latency_s_mean=_opt_float(d.get("latency_s_mean")),
            human_verified=None if d.get("human_verified") is None else bool(d["human_verified"]),
            human_corrections=_opt_int(d.get("human_corrections")),
            raw_hash=sha256_text(canonical_json(dict(d))),
        )


def import_benchmark_ledger(
    path: str | Path, *, on_event: EventFn | None = None
) -> Iterator[AggregateRow]:
    """Read an Athena ``benchmark_ledger.jsonl`` into :class:`AggregateRow`\\ s.

    These never enter the grade ledger — see :class:`AggregateRow` for why.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            raw = json.loads(text)
            if not isinstance(raw, Mapping):
                raise LegacyImportError(f"{p.name} line {line_no}: not an object")
            row = AggregateRow.from_benchmark_row(raw)
            _emit(
                on_event,
                "legacy.aggregate",
                line=line_no,
                capability_class=row.capability_class,
                model=row.model,
                n_samples=row.n_samples,
            )
            yield row


__all__ = [
    "AGGREGATE_SCHEMA",
    "BENCHMARK_LEDGER_PROVENANCE",
    "CENSUS_APPARATUS_VERSION",
    "CENSUS_BUILDER",
    "CENSUS_DEFAULT_MODEL",
    "CENSUS_IMPORT_CREATED",
    "CENSUS_PROVENANCE",
    "CENSUS_PROVIDER",
    "CENSUS_SOURCE",
    "IMPORTED_EVIDENCE_SCHEMA",
    "AggregateRow",
    "ImportedGrade",
    "LegacyImportError",
    "canonical_size",
    "import_benchmark_ledger",
    "import_census",
    "import_census_grades",
    "import_census_tasks",
    "import_repo_configs",
    "imported_pack",
    "imported_pack_hash",
]
