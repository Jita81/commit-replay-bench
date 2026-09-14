"""Request / response models for ``/reviews`` and the retained-artefact drill-down.

A review is a human's post-hoc verdict on ONE graded row (:mod:`crb.core.review`),
ledgered against the row's chain hash and anchored to the exact patch bytes the
reviewer read (``patch_sha256`` must equal the row's evidence pack ``diff_sha256``).
Lives beside :mod:`crb.server.schemas` (another workstream's file this wave); every
field here is a core ``to_dict`` value re-typed so the OpenAPI document is honest.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from crb.core.review import FINDING_KINDS, VERDICTS, is_sha256

_SHA256_LEN = 64


def _hex64(v: str, name: str) -> str:
    v = v.strip().lower()
    if not is_sha256(v):
        raise ValueError(f"{name} must be a 64-character hex SHA-256")
    return v


class FindingIn(BaseModel):
    """One thing the reviewer saw: ``kind`` in ``crb.core.review.FINDING_KINDS``."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    note: str = Field(min_length=1, max_length=4000)
    file: str = Field(default="", max_length=512)
    line: int | None = Field(default=None, ge=1)

    @field_validator("kind")
    @classmethod
    def _kind_known(cls, v: str) -> str:
        if v not in FINDING_KINDS:
            raise ValueError(f"finding kind must be one of {FINDING_KINDS}")
        return v

    @field_validator("note")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("note must not be blank")
        return v.strip()


class ReviewCreateRequest(BaseModel):
    """``POST /reviews``. The verdict is DERIVED from the findings by the core's one
    rule (most severe kind; ``ok`` with none); a ``verdict`` sent by the client must
    agree (422 otherwise). ``patch_sha256`` is the hash of the patch the reviewer
    loaded — it must equal the row's pack ``diff_sha256`` (422 ``review_refused`` /
    ``patch_hash_mismatch``). ``not_reviewed: true`` records that the reviewer looked
    and could not review: no findings, no ``mergeable``, no hash."""

    model_config = ConfigDict(extra="forbid")

    grade_row_hash: str = Field(min_length=_SHA256_LEN, max_length=_SHA256_LEN)
    statement: str = Field(min_length=1, max_length=8000)
    findings: list[FindingIn] = Field(default_factory=list, max_length=200)
    mergeable: bool | None = None
    patch_sha256: str = Field(default="", max_length=_SHA256_LEN)
    not_reviewed: bool = False
    verdict: str | None = None

    @field_validator("grade_row_hash")
    @classmethod
    def _row_hex(cls, v: str) -> str:
        return _hex64(v, "grade_row_hash")

    @field_validator("patch_sha256")
    @classmethod
    def _patch_hex(cls, v: str) -> str:
        return _hex64(v, "patch_sha256") if v.strip() else ""

    @field_validator("statement")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("statement must not be blank")
        return v.strip()

    @field_validator("verdict")
    @classmethod
    def _verdict_known(cls, v: str | None) -> str | None:
        if v is not None and v not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}")
        return v


class FindingOut(BaseModel):
    kind: str
    note: str
    file: str
    line: int | None


class ReviewOut(BaseModel):
    """:meth:`crb.core.review.ReviewRecord.to_dict` + the reviewed task's subject and
    the reviewed row's verdict (``grade_clean``) so a list reads without a second call."""

    model_config = ConfigDict(populate_by_name=True)

    review_id: str
    schema_: str = Field(alias="schema")
    grade_row_hash: str
    repo: str
    task_id: str
    subject: str = ""
    grade_clean: bool | None = None
    reviewer: str
    verdict: str
    findings: list[FindingOut]
    mergeable: bool | None
    statement: str
    patch_sha256_reviewed: str
    evidence_pack_hash: str
    apparatus_version: str
    created: str
    prev_hash: str
    row_hash: str


class ReviewVerifyOut(BaseModel):
    """``GET /reviews/verify`` — never raises: walks the ``reviews`` chain recomputing
    every ``row_hash`` from the stored columns; ``anchored`` counts reviews whose
    ``patch_sha256_reviewed`` still equals their row's pack ``diff_sha256`` (a
    ``not_reviewed`` record is not counted either way)."""

    rows: int
    ok: bool
    chain_ok: bool
    broken_at: int | None
    detail: str
    anchored: int
    unanchored: int
    verified_at: str


class ReviewCellStatsOut(BaseModel):
    """:meth:`crb.core.review.ReviewCellStats.to_dict` — one cell's human coverage."""

    process_step: str
    capability_class: str
    size: str
    language: str
    builder: str
    model: str
    provider: str
    n_rows: int
    n_reviewed: int
    n_review_defects: int
    reviewed_share: float
    n_ok: int
    n_defect: int
    n_regression: int
    n_api_change: int
    n_style: int
    n_not_reviewed: int
    n_mergeable: int
    n_not_mergeable: int


class ReviewStatsOut(BaseModel):
    """``GET /reviews/stats`` — the human verdicts joined onto the repo's cells under
    the same ``by`` projection ``/capability-map`` uses."""

    repo: str
    by: list[str]
    n_reviews: int
    cells: list[ReviewCellStatsOut]


class RetainedArtefactStatus(BaseModel):
    """What ``/grades/{row_hash}`` retained: answered on the patch / transcript routes'
    404 envelope ``detail`` and by ``GET /grades/{row_hash}/retained``."""

    row_hash: str
    run_id: str
    retain_worktrees: bool
    retain_transcripts: bool
    patch_available: bool
    patch_reason: str
    transcript_available: bool
    transcript_reason: str
    diff_sha256: str
    extra: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "FindingIn",
    "FindingOut",
    "RetainedArtefactStatus",
    "ReviewCellStatsOut",
    "ReviewCreateRequest",
    "ReviewOut",
    "ReviewStatsOut",
    "ReviewVerifyOut",
]
