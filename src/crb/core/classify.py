"""Two class axes, one resolution rule.

A task's ``capability_class`` — the class axis of every cell key, ledger row and
capability-map cell — is **resolved** from two independent sources:

* the **path class** (:func:`crb.core.spec.classify_commit`): deterministic, free,
  derived from where the change lands. Blind to intent: a behaviour change and a
  feature in ``command.go`` are both ``bug.fix``;
* the **intent label** (:class:`IntentLabel`): a judgement of *what kind* of change
  the commit is, made by a model shown only the commit's subject, message, changed
  paths and diff statistics (never the diff body — the label must not leak the
  implementation into a task the same model may later be asked to reproduce), or
  by a human auditing a sample.

Precedence (:func:`resolve`) is deterministic and total::

    human label            → wins outright (``source = "human"``)
    intent ≥ min_confidence
      and not unclassified → wins            (``source = "intent"``)
    otherwise              → the path class   (``source = "path"``)

The winner is recorded (:class:`Resolution.source`) so ``crb tasks classes`` can
show a reviewer which axis produced every class, and a label carries the sha256
of the exact evidence it was made from (:attr:`IntentLabel.evidence_hash`), so a
label made on stale evidence is detectable.

Vocabulary is closed (:mod:`crb.core.taxonomy`): a label names a member of
:data:`~crb.core.taxonomy.CLASS_VOCABULARY` or :data:`~crb.core.taxonomy.UNCLASSIFIED`.
Nothing here calls a model; :mod:`crb.builders.labeller` does, through
:class:`Labeller`.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from crb.core.redact import redact
from crb.core.taxonomy import (
    CLASS_DEFINITIONS,
    CLASS_VOCABULARY,
    UNCLASSIFIED,
    is_explicit_unclassified,
    is_known_class,
    normalise_class,
)

if TYPE_CHECKING:
    from crb.core.git import GitRepo

LABEL_SCHEMA = "crb.intent-label.v1"

#: Below this confidence an intent label does not displace the path class.
DEFAULT_MIN_CONFIDENCE = 0.7

#: ``labeller`` prefix that marks a human judgement (highest precedence).
HUMAN_LABELLER_PREFIX = "human:"

SOURCE_HUMAN = "human"
SOURCE_INTENT = "intent"
SOURCE_PATH = "path"
CLASS_SOURCES: tuple[str, ...] = (SOURCE_HUMAN, SOURCE_INTENT, SOURCE_PATH)

#: Caps on what a label may carry (redacted first).
MESSAGE_CAP = 4000
SUBJECT_CAP = 200
RATIONALE_CAP = 600
PATHS_CAP = 200


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Evidence: the exact inputs a labeller is shown
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathStat:
    """One changed path with its added/deleted line counts (``git diff --numstat``).
    Binary files count 0/0 — the counts are context, never the diff."""

    path: str
    added: int = 0
    deleted: int = 0

    def __post_init__(self) -> None:
        if self.added < 0 or self.deleted < 0:
            raise ValueError("line counts cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "added": self.added, "deleted": self.deleted}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PathStat:
        return cls(str(d["path"]), int(d.get("added", 0)), int(d.get("deleted", 0)))


@dataclass(frozen=True)
class LabelEvidence:
    """Everything a labeller is shown, and nothing else.

    Invariant: :meth:`digest` is the sha256 of :meth:`to_dict` in canonical JSON, so
    two labels made from byte-identical evidence share an ``evidence_hash`` and a
    label made on different evidence (a re-mined task, an edited message) does not.
    The message is redacted and capped *here*, so what is hashed is what is shown.
    """

    subject: str
    message: str
    changed_paths: tuple[str, ...]
    diff_stats: tuple[PathStat, ...]
    path_class: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", redact(self.subject)[:SUBJECT_CAP])
        object.__setattr__(self, "message", redact(self.message)[:MESSAGE_CAP])
        object.__setattr__(self, "changed_paths", tuple(self.changed_paths)[:PATHS_CAP])
        object.__setattr__(self, "diff_stats", tuple(self.diff_stats)[:PATHS_CAP])
        if not is_known_class(self.path_class):
            raise ValueError(f"path_class {self.path_class!r} is not in the vocabulary")

    @property
    def churn(self) -> int:
        return sum(s.added + s.deleted for s in self.diff_stats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "message": self.message,
            "changed_paths": list(self.changed_paths),
            "diff_stats": [s.to_dict() for s in self.diff_stats],
            "path_class": self.path_class,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> LabelEvidence:
        return cls(
            subject=str(d.get("subject", "")),
            message=str(d.get("message", "")),
            changed_paths=tuple(str(p) for p in d.get("changed_paths", ())),
            diff_stats=tuple(PathStat.from_dict(s) for s in d.get("diff_stats", ())),
            path_class=str(d.get("path_class") or UNCLASSIFIED),
        )

    def digest(self) -> str:
        return _sha256(_canonical(self.to_dict()))


def evidence_hash(
    subject: str,
    message: str,
    diff_stats: Sequence[PathStat],
    changed_paths: Sequence[str],
    path_class: str,
) -> str:
    """The hash a :class:`Labeller` must stamp: sha256 of exactly these inputs."""
    return LabelEvidence(
        subject=subject,
        message=message,
        changed_paths=tuple(changed_paths),
        diff_stats=tuple(diff_stats),
        path_class=path_class,
    ).digest()


def commit_evidence(repo: GitRepo, sha: str, *, path_class: str) -> LabelEvidence:
    """Read a commit's label evidence from git: subject, full message, per-path
    numstat against the first parent. Never the diff text."""
    subject = repo.subject(sha)
    message = repo.message(sha)
    out = repo.run("diff", "--numstat", f"{sha}~1", sha, check=True).stdout
    stats: list[PathStat] = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        stats.append(PathStat(path, int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0))
    return LabelEvidence(
        subject=subject,
        message=message,
        changed_paths=tuple(s.path for s in stats),
        diff_stats=tuple(stats),
        path_class=path_class,
    )


# ---------------------------------------------------------------------------
# The label
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntentLabel:
    """One judgement of a commit's change class.

    Invariants: ``intent_class`` is a vocabulary member or :data:`UNCLASSIFIED`;
    ``confidence`` is a finite number in ``[0, 1]``; ``labeller`` names who judged
    (``"claude_code:claude-sonnet-5"``, ``"openai_agent:gpt-oss-120b@cerebras"``,
    ``"human:<user>"``); ``rationale`` is redacted and capped; ``evidence_hash`` is
    the digest of the evidence shown (``""`` only for a human label made without
    the evidence at hand — recorded honestly, never invented).
    """

    intent_class: str
    confidence: float
    rationale: str
    labeller: str
    labelled_at: str = field(default_factory=utc_now_iso)
    evidence_hash: str = ""
    schema: str = LABEL_SCHEMA

    def __post_init__(self) -> None:
        if not is_known_class(self.intent_class):
            raise ValueError(
                f"intent_class {self.intent_class!r} is not in the closed vocabulary "
                f"(normalise it first: crb.core.taxonomy.normalise_class)"
            )
        conf = float(self.confidence)
        if not math.isfinite(conf) or not 0.0 <= conf <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence!r}")
        object.__setattr__(self, "confidence", round(conf, 4))
        if not self.labeller or not self.labeller.strip():
            raise ValueError("a label needs a labeller")
        object.__setattr__(self, "labeller", self.labeller.strip())
        object.__setattr__(self, "rationale", redact(str(self.rationale or ""))[:RATIONALE_CAP])
        if not self.labelled_at:
            object.__setattr__(self, "labelled_at", utc_now_iso())

    @property
    def is_human(self) -> bool:
        return self.labeller.startswith(HUMAN_LABELLER_PREFIX)

    @property
    def unclassified(self) -> bool:
        return self.intent_class == UNCLASSIFIED

    def confident(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> bool:
        return not self.unclassified and self.confidence >= min_confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "intent_class": self.intent_class,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "labeller": self.labeller,
            "labelled_at": self.labelled_at,
            "evidence_hash": self.evidence_hash,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> IntentLabel:
        return cls(
            intent_class=normalise_class(d.get("intent_class")),
            confidence=float(d.get("confidence", 0.0) or 0.0),
            rationale=str(d.get("rationale", "") or ""),
            labeller=str(d.get("labeller", "") or ""),
            labelled_at=str(d.get("labelled_at", "") or ""),
            evidence_hash=str(d.get("evidence_hash", "") or ""),
            schema=str(d.get("schema") or LABEL_SCHEMA),
        )


def human_label(
    intent_class: str, *, by: str, rationale: str = "", evidence_hash: str = ""
) -> IntentLabel:
    """A human's judgement: confidence 1.0, labeller ``human:<by>``. The class must
    be a vocabulary member or an explicit "unclassified" (a human cannot invent a
    class either)."""
    cls = normalise_class(intent_class)
    if cls == UNCLASSIFIED and not is_explicit_unclassified(intent_class):
        raise ValueError(
            f"class {intent_class!r} is not in the vocabulary {list(CLASS_VOCABULARY)}"
        )
    who = by.strip()
    if not who:
        raise ValueError("a human label needs --by <name>")
    return IntentLabel(
        intent_class=cls,
        confidence=1.0,
        rationale=rationale,
        labeller=f"{HUMAN_LABELLER_PREFIX}{who}",
        evidence_hash=evidence_hash,
    )


def unclassified_label(labeller: str, *, reason: str, evidence_hash: str = "") -> IntentLabel:
    """The fail-closed label: a model that returned nothing usable classifies
    nothing (confidence 0) and the path class stands."""
    return IntentLabel(
        intent_class=UNCLASSIFIED,
        confidence=0.0,
        rationale=reason,
        labeller=labeller,
        evidence_hash=evidence_hash,
    )


# ---------------------------------------------------------------------------
# Labeller contract + the reply parser every labeller shares
# ---------------------------------------------------------------------------


@runtime_checkable
class Labeller(Protocol):
    """Anything that turns label evidence into an :class:`IntentLabel`.

    ``name`` is what the label's ``labeller`` field records. ``label`` must be
    total: a transport or parse failure yields :func:`unclassified_label`, never
    an exception (one bad commit must not kill a labelling run).
    """

    @property
    def name(self) -> str: ...

    def label(
        self,
        *,
        subject: str,
        message: str,
        diff_stats: Sequence[PathStat],
        changed_paths: Sequence[str],
        path_class: str,
    ) -> IntentLabel: ...


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_label_reply(text: str, *, labeller: str, evidence_hash: str) -> IntentLabel:
    """Turn a model's reply into a label, deterministically.

    Accepts a bare JSON object, a fenced one, or one embedded in prose (the first
    ``{ … }`` span). Keys: ``class`` (or ``intent_class``), ``confidence`` (number
    or numeric string in ``[0, 1]``; out-of-range clamps), ``rationale``. Any
    shape that does not yield a vocabulary class is :data:`UNCLASSIFIED` with
    confidence 0 and the failure named in the rationale. Never raises.
    """
    raw = (text or "").strip()
    obj: Any = None
    candidates = [raw]
    m = _JSON_OBJECT_RE.search(raw)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            break
        obj = None
    if not isinstance(obj, dict):
        return unclassified_label(
            labeller, reason="malformed reply: no JSON object", evidence_hash=evidence_hash
        )
    raw_class = obj.get("class", obj.get("intent_class"))
    cls = normalise_class(raw_class)
    try:
        conf = float(obj.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if not math.isfinite(conf):
        conf = 0.0
    conf = min(1.0, max(0.0, conf))
    rationale = str(obj.get("rationale", "") or "")
    if cls == UNCLASSIFIED:
        if raw_class in (None, ""):
            why = "no class in reply"
        elif is_explicit_unclassified(raw_class):
            why = f"labeller answered {raw_class!r}"
        else:
            why = f"unknown class {raw_class!r}"
        return unclassified_label(
            labeller,
            reason=why + (": " + rationale if rationale else ""),
            evidence_hash=evidence_hash,
        )
    return IntentLabel(
        intent_class=cls,
        confidence=conf,
        rationale=rationale,
        labeller=labeller,
        evidence_hash=evidence_hash,
    )


def render_label_prompt(evidence: LabelEvidence) -> str:
    """The instrument's prompt: the closed vocabulary with definitions, then the
    evidence — subject, message, per-path stats — and the answer contract. Contains
    no diff body by construction (the evidence type has none)."""
    vocab = "\n".join(f"- {c}: {CLASS_DEFINITIONS[c]}" for c in CLASS_VOCABULARY)
    stats = "\n".join(
        f"- {s.path}  (+{s.added} / -{s.deleted})" for s in evidence.diff_stats
    ) or "\n".join(f"- {p}" for p in evidence.changed_paths)
    return (
        "Classify the KIND of change this git commit makes. Pick exactly ONE class from the "
        "closed vocabulary below, or 'unclassified' if none fits. Judge intent (what the "
        "author set out to change), not location. Prefer the artefact classes (docs, ci, "
        "infra, test, migration, route, model, component) only when the change is confined "
        "to that artefact; otherwise choose among bug.fix / feature.add / behavior.change / "
        "refactor / perf.\n\n"
        f"VOCABULARY\n{vocab}\n\n"
        f"COMMIT SUBJECT\n{evidence.subject or '(none)'}\n\n"
        f"COMMIT MESSAGE\n{evidence.message or '(none)'}\n\n"
        f"CHANGED PATHS (lines added / deleted; the diff itself is withheld)\n"
        f"{stats or '(none)'}\n\n"
        f"PATH-DERIVED CLASS (a location heuristic, may be wrong): {evidence.path_class}\n\n"
        "Answer with ONE JSON object and nothing else:\n"
        '{"class": "<vocabulary member or unclassified>", '
        '"confidence": <0.0-1.0>, "rationale": "<one sentence>"}'
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """Which axis produced ``capability_class`` and why."""

    capability_class: str
    source: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "capability_class": self.capability_class,
            "source": self.source,
            "reason": self.reason,
        }


def resolve(
    path_class: str,
    intent: IntentLabel | None,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> Resolution:
    """The precedence rule (see the module docstring). Deterministic and total."""
    if intent is not None and intent.is_human:
        return Resolution(intent.intent_class, SOURCE_HUMAN, f"human label by {intent.labeller}")
    if intent is None:
        return Resolution(path_class, SOURCE_PATH, "no intent label")
    if intent.unclassified:
        return Resolution(path_class, SOURCE_PATH, f"intent unclassified ({intent.labeller})")
    if intent.confidence < min_confidence:
        return Resolution(
            path_class,
            SOURCE_PATH,
            f"intent {intent.intent_class} below threshold "
            f"({intent.confidence:.2f} < {min_confidence:.2f})",
        )
    return Resolution(
        intent.intent_class,
        SOURCE_INTENT,
        f"intent {intent.confidence:.2f} ≥ {min_confidence:.2f} ({intent.labeller})",
    )


def resolve_class(
    path_class: str,
    intent: IntentLabel | None,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> str:
    """``resolve(...).capability_class`` — the string every consumer keys on."""
    return resolve(path_class, intent, min_confidence=min_confidence).capability_class


# ---------------------------------------------------------------------------
# Summaries (for a run's counts and the audit table)
# ---------------------------------------------------------------------------


def label_summary(labels: Iterable[IntentLabel | None]) -> dict[str, Any]:
    """Per-class counts, mean confidence over the labelled, the unclassified and
    unlabelled tallies — every number with its n."""
    items = list(labels)
    present = [x for x in items if x is not None]
    classes: dict[str, int] = {}
    for x in present:
        classes[x.intent_class] = classes.get(x.intent_class, 0) + 1
    confs = [x.confidence for x in present if not x.unclassified]
    return {
        "n": len(items),
        "labelled": len(present),
        "unlabelled": len(items) - len(present),
        "unclassified": sum(1 for x in present if x.unclassified),
        "human": sum(1 for x in present if x.is_human),
        "classes": dict(sorted(classes.items())),
        "mean_confidence": round(sum(confs) / len(confs), 4) if confs else None,
        "mean_confidence_n": len(confs),
    }


__all__ = [
    "CLASS_SOURCES",
    "DEFAULT_MIN_CONFIDENCE",
    "HUMAN_LABELLER_PREFIX",
    "LABEL_SCHEMA",
    "SOURCE_HUMAN",
    "SOURCE_INTENT",
    "SOURCE_PATH",
    "IntentLabel",
    "LabelEvidence",
    "Labeller",
    "PathStat",
    "Resolution",
    "commit_evidence",
    "evidence_hash",
    "human_label",
    "label_summary",
    "parse_label_reply",
    "render_label_prompt",
    "resolve",
    "resolve_class",
    "unclassified_label",
    "utc_now_iso",
]
