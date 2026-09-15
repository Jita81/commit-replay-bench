"""crb.core.classify + crb.core.taxonomy — the closed vocabulary, the label, the
evidence hash, the reply parser, the prompt (no diff body), and the precedence rule.

Navigation
----------
What it is:   The intent-label test suite — the closed vocabulary, ``IntentLabel``, the evidence
              hash, the reply parser, the prompt and the precedence rule.
What it does: Pins that the vocabulary is exactly path ∪ intent classes with one definition each
              and covers every census label, that an unknown class is refused (explicit
              ``unclassified`` is not), that the evidence digest is deterministic, redacted and
              capped before hashing and reads git WITHOUT the diff body, that ``parse_label_reply``
              never raises, that the prompt shows vocabulary and evidence but no diff, and that
              resolution is human > intent > path, deterministically.
How:          Pure cases over ``crb.core.classify`` / ``crb.core.taxonomy``; one case runs on
              ``pyrepo`` for the git-backed evidence.
Layer:        tests — docs/ARCHITECTURE.md#75-change-class-two-axes-one-resolved-value
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/classify.py and src/crb/core/taxonomy.py (under test),
              src/crb/core/spec.py (where the resolved class lands), tests/test_builders_labeller.py
              (the LLM labellers that produce the label), tests/test_worker_label.py (the run
              kind that stores it)
Tested by:    tests/test_classify.py
Touch when:   a class is added to the vocabulary (definition + census-coverage case); the prompt
              or reply shape changes (the no-diff rule must survive).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core import classify as c
from crb.core import taxonomy as tx
from crb.core.spec import ALL_CLASSES, CLASS_VOCABULARY, INTENT_CLASSES, UNCLASSIFIED
from fixtures import pyrepo as pr

_CENSUS = Path(__file__).resolve().parents[1] / "data" / "census-2026-07-08" / "class_labels.json"

# ---------------------------------------------------------------------------
# taxonomy: closed, defined, census-compatible
# ---------------------------------------------------------------------------


def test_vocabulary_is_the_union_of_path_and_intent_classes_and_closed() -> None:
    assert set(CLASS_VOCABULARY) == set(ALL_CLASSES) | set(INTENT_CLASSES)
    assert list(CLASS_VOCABULARY) == sorted(set(CLASS_VOCABULARY))
    assert len(ALL_CLASSES) == 14 and len(INTENT_CLASSES) == 4 and len(CLASS_VOCABULARY) == 18
    assert UNCLASSIFIED not in CLASS_VOCABULARY
    # spec re-exports the same objects (one source of truth)
    assert ALL_CLASSES is tx.ALL_CLASSES and CLASS_VOCABULARY is tx.CLASS_VOCABULARY


def test_every_vocabulary_member_has_exactly_one_definition() -> None:
    assert set(tx.CLASS_DEFINITIONS) == set(CLASS_VOCABULARY)
    assert all(d.strip() and len(d) < 240 for d in tx.CLASS_DEFINITIONS.values())


def test_census_class_labels_are_covered_by_the_vocabulary() -> None:
    """The essay's per-class numbers were measured on these labels: every one of
    them must be a vocabulary member (``other`` is the explicit unclassified)."""
    labels = json.loads(_CENSUS.read_text(encoding="utf-8"))
    used = set(labels.values())
    assert used == {"bug.fix", "feature.add", "refactor", "perf", "behavior.change", "other"}
    for raw in used:
        norm = tx.normalise_class(raw)
        assert norm in CLASS_VOCABULARY or (raw == "other" and norm == UNCLASSIFIED)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("bug.fix", "bug.fix"),
        (" Feature.Add ", "feature.add"),
        ('"refactor"', "refactor"),
        ("`perf`", "perf"),
        ("behaviour.change", "behavior.change"),
        ("behavior_change", "behavior.change"),
        ("feat", "feature.add"),
        ("bugfix", "bug.fix"),
        ("docs", "docs.update"),
        ("other", UNCLASSIFIED),
        ("unclassified", UNCLASSIFIED),
        (UNCLASSIFIED, UNCLASSIFIED),
        ("", UNCLASSIFIED),
        (None, UNCLASSIFIED),
        ("security.fix", UNCLASSIFIED),  # invented class: closed vocabulary
        (42, UNCLASSIFIED),
    ],
)
def test_normalise_class(raw: object, expected: str) -> None:
    assert tx.normalise_class(raw) == expected


def test_explicit_unclassified_vs_invented() -> None:
    assert tx.is_explicit_unclassified("Other") and tx.is_explicit_unclassified("none")
    assert not tx.is_explicit_unclassified("security.fix")
    assert tx.is_known_class("bug.fix") and tx.is_known_class(UNCLASSIFIED)
    assert not tx.is_known_class("other") and not tx.is_known_class("")


# ---------------------------------------------------------------------------
# IntentLabel
# ---------------------------------------------------------------------------


def test_intent_label_invariants() -> None:
    lab = c.IntentLabel("feature.add", 0.91234, "adds a thing", " claude_code:claude-sonnet-5 ")
    assert lab.confidence == 0.9123 and lab.labeller == "claude_code:claude-sonnet-5"
    assert lab.labelled_at and lab.schema == c.LABEL_SCHEMA and not lab.is_human
    assert lab.confident() and not lab.confident(0.95)
    with pytest.raises(ValueError, match="closed vocabulary"):
        c.IntentLabel("security.fix", 0.9, "", "m")
    with pytest.raises(ValueError, match="confidence"):
        c.IntentLabel("bug.fix", 1.5, "", "m")
    with pytest.raises(ValueError, match="confidence"):
        c.IntentLabel("bug.fix", float("nan"), "", "m")
    with pytest.raises(ValueError, match="labeller"):
        c.IntentLabel("bug.fix", 0.5, "", "  ")


def test_intent_label_round_trip_and_redaction() -> None:
    lab = c.IntentLabel(
        "refactor",
        0.8,
        "token=abcdefgh12345678 was in the message; " + "x" * 2000,
        "human:paul",
        labelled_at="2026-09-13T10:00:00+00:00",
        evidence_hash="ab" * 32,
    )
    assert "[REDACTED]" in lab.rationale and "abcdefgh12345678" not in lab.rationale
    assert len(lab.rationale) <= c.RATIONALE_CAP
    d = lab.to_dict()
    json.dumps(d)
    assert c.IntentLabel.from_dict(d) == lab
    # from_dict normalises spellings and tolerates missing optionals
    loose = c.IntentLabel.from_dict({"intent_class": "Behaviour.Change", "labeller": "m"})
    assert loose.intent_class == "behavior.change" and loose.confidence == 0.0
    assert loose.labelled_at  # filled in


def test_human_and_unclassified_labels() -> None:
    h = c.human_label("perf", by=" paul ", rationale="measured")
    assert h.is_human and h.confidence == 1.0 and h.labeller == "human:paul"
    assert c.human_label("other", by="p").unclassified  # explicit none-of-these is honest
    with pytest.raises(ValueError, match="not in the vocabulary"):
        c.human_label("security.fix", by="p")
    with pytest.raises(ValueError, match="--by"):
        c.human_label("perf", by="   ")
    u = c.unclassified_label("m:x", reason="model_error: boom", evidence_hash="ff" * 32)
    assert u.unclassified and u.confidence == 0.0 and u.rationale.startswith("model_error")


# ---------------------------------------------------------------------------
# Evidence + hash
# ---------------------------------------------------------------------------


def _ev(**kw: object) -> c.LabelEvidence:
    base: dict[str, object] = {
        "subject": "Remove the default completion cmd if it is alone",
        "message": "When a program has no sub-commands …",
        "changed_paths": ("command.go", "completions.go", "completions_test.go"),
        "diff_stats": (
            c.PathStat("command.go", 8, 7),
            c.PathStat("completions.go", 28, 2),
            c.PathStat("completions_test.go", 141, 3),
        ),
        "path_class": "bug.fix",
    }
    base.update(kw)
    return c.LabelEvidence(**base)  # type: ignore[arg-type]


def test_evidence_digest_is_deterministic_and_sensitive() -> None:
    a, b = _ev(), _ev()
    assert (
        a.digest()
        == b.digest()
        == c.evidence_hash(a.subject, a.message, a.diff_stats, a.changed_paths, a.path_class)
    )
    assert _ev(message="different").digest() != a.digest()
    assert _ev(path_class="feature.add").digest() != a.digest()
    assert _ev(diff_stats=(c.PathStat("command.go", 9, 7),)).digest() != a.digest()
    assert a.churn == 8 + 7 + 28 + 2 + 141 + 3
    assert c.LabelEvidence.from_dict(a.to_dict()) == a


def test_evidence_is_redacted_and_capped_before_hashing() -> None:
    ev = _ev(message="Authorization: Bearer abcdefghijklmnop\n" + "y" * 10_000)
    assert "abcdefghijklmnop" not in ev.message and len(ev.message) == c.MESSAGE_CAP
    with pytest.raises(ValueError, match="not in the vocabulary"):
        _ev(path_class="nope")
    with pytest.raises(ValueError, match="negative"):
        c.PathStat("x", -1, 0)


def test_commit_evidence_reads_git_without_the_diff(pyrepo: pr.PyRepo) -> None:
    ev = c.commit_evidence(pyrepo.repo, pyrepo.feat_sha, path_class="bug.fix")
    assert ev.subject == "feat: add subtract"
    assert ev.message.startswith("feat: add subtract")
    assert set(ev.changed_paths) == {pr.SRC, pr.TEST_SUBTRACT}
    by_path = {s.path: s for s in ev.diff_stats}
    assert by_path[pr.SRC].added == pr.FEAT_SRC_CHURN and by_path[pr.SRC].deleted == 0
    assert "def subtract" not in json.dumps(ev.to_dict())  # never the code


# ---------------------------------------------------------------------------
# Reply parsing (deterministic, total)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cls", "conf"),
    [
        ('{"class": "feature.add", "confidence": 0.9, "rationale": "adds"}', "feature.add", 0.9),
        (
            '```json\n{"class":"behavior.change","confidence":"0.75","rationale":"x"}\n```',
            "behavior.change",
            0.75,
        ),
        ('Sure! {"class": "Refactor", "confidence": 1.7} done', "refactor", 1.0),
        ('{"intent_class": "perf", "confidence": -3}', "perf", 0.0),
        ('{"class": "bug.fix"}', "bug.fix", 0.0),
    ],
)
def test_parse_label_reply_accepts_reasonable_shapes(text: str, cls: str, conf: float) -> None:
    lab = c.parse_label_reply(text, labeller="m", evidence_hash="e" * 64)
    assert lab.intent_class == cls and lab.confidence == conf
    assert lab.labeller == "m" and lab.evidence_hash == "e" * 64


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("", "malformed reply"),
        ("I think this is a feature.", "malformed reply"),
        ("[1, 2]", "malformed reply"),
        ('{"class": "security.fix", "confidence": 0.9}', "unknown class 'security.fix'"),
        (
            '{"class": "other", "confidence": 0.9, "rationale": "none fit"}',
            "labeller answered 'other'",
        ),
        ('{"confidence": 0.9}', "no class in reply"),
        ('{"class": "bug.fix", "confidence": "high"}', ""),  # bad confidence → 0, class kept
    ],
)
def test_parse_label_reply_never_raises_on_bad_output(text: str, why: str) -> None:
    lab = c.parse_label_reply(text, labeller="m", evidence_hash="")
    if why:
        assert lab.unclassified and lab.confidence == 0.0 and why in lab.rationale
    else:
        assert lab.intent_class == "bug.fix" and lab.confidence == 0.0


def test_render_prompt_shows_vocabulary_evidence_and_no_diff_body() -> None:
    ev = _ev()
    prompt = c.render_label_prompt(ev)
    for cls in CLASS_VOCABULARY:
        assert f"- {cls}: {tx.CLASS_DEFINITIONS[cls]}" in prompt
    assert ev.subject in prompt and ev.message in prompt
    assert "- completions.go  (+28 / -2)" in prompt
    assert "PATH-DERIVED CLASS (a location heuristic, may be wrong): bug.fix" in prompt
    assert '"class"' in prompt and "unclassified" in prompt
    # the evidence type cannot carry a diff, so no hunk markers can ever appear
    assert "@@" not in prompt and "+++ b/" not in prompt and "diff --git" not in prompt


# ---------------------------------------------------------------------------
# Resolution: human > confident intent > path
# ---------------------------------------------------------------------------


def _lab(cls: str, conf: float, who: str = "claude_code:m") -> c.IntentLabel:
    return c.IntentLabel(cls, conf, "r", who)


def test_resolution_precedence_table() -> None:
    assert c.resolve("bug.fix", None) == c.Resolution("bug.fix", "path", "no intent label")
    r = c.resolve("bug.fix", _lab("feature.add", 0.7))
    assert (r.capability_class, r.source) == ("feature.add", "intent")
    r = c.resolve("bug.fix", _lab("feature.add", 0.69))
    assert (r.capability_class, r.source) == ("bug.fix", "path") and "below threshold" in r.reason
    r = c.resolve("bug.fix", _lab("feature.add", 0.69), min_confidence=0.5)
    assert r.source == "intent"
    r = c.resolve("bug.fix", _lab(UNCLASSIFIED, 0.0))
    assert (r.capability_class, r.source) == ("bug.fix", "path") and "unclassified" in r.reason
    # a human wins outright, whatever the confidence or class — even "none of these"
    r = c.resolve("bug.fix", _lab("perf", 0.1, "human:paul"))
    assert (r.capability_class, r.source) == ("perf", "human")
    r = c.resolve("bug.fix", c.human_label("other", by="paul"))
    assert (r.capability_class, r.source) == (UNCLASSIFIED, "human")
    assert c.resolve_class("docs.update", _lab("bug.fix", 0.99)) == "bug.fix"
    assert c.resolve_class(UNCLASSIFIED, None) == UNCLASSIFIED
    assert set(c.CLASS_SOURCES) == {"human", "intent", "path"}
    assert c.Resolution("x", "path", "y").to_dict() == {
        "capability_class": "x",
        "source": "path",
        "reason": "y",
    }


def test_resolution_is_deterministic() -> None:
    args = ("bug.fix", _lab("behavior.change", 0.83))
    assert [c.resolve(*args) for _ in range(5)] == [c.resolve(*args)] * 5


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_label_summary_carries_every_n() -> None:
    s = c.label_summary(
        [
            _lab("feature.add", 0.9),
            _lab("feature.add", 0.7),
            _lab("bug.fix", 0.8, "human:p"),
            _lab(UNCLASSIFIED, 0.0),
            None,
        ]
    )
    assert s == {
        "n": 5,
        "labelled": 4,
        "unlabelled": 1,
        "unclassified": 1,
        "human": 1,
        "classes": {UNCLASSIFIED: 1, "bug.fix": 1, "feature.add": 2},
        "mean_confidence": 0.8,
        "mean_confidence_n": 3,
    }
    assert c.label_summary([])["mean_confidence"] is None


def test_labeller_protocol_is_runtime_checkable() -> None:
    class Fake:
        name = "fake:m"

        def label(self, **_: object) -> c.IntentLabel:
            return c.unclassified_label(self.name, reason="fake")

    assert isinstance(Fake(), c.Labeller)
    assert not isinstance(object(), c.Labeller)
