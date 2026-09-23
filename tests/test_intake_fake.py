"""crb.intake.fake — the file-backed board the walkthrough drives, and its gate.

Navigation
----------
What it is:   The fake tracker's suite: the environment gate, protocol conformance, and
              that it behaves like a real tracker rather than a kinder one.
What it does: Pins that the fake is refused unless ``CRB_ENABLE_FAKE_TRACKER=1`` is set,
              that it satisfies the same protocol the real adapters do, that a repeated
              comment writes nothing, that a label replaces the product's own and leaves
              other people's alone, and that a workflow it was told to refuse refuses.
How:          One JSON document under ``tmp_path``; no network anywhere.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/fake.py (under test), src/crb/intake/client.py (the protocol),
              src/crb/server/intake.py (``build_tracker``'s gate),
              ui/e2e/walkthrough/12-intake.spec.ts (the spec that drives it)
Tested by:    tests/test_intake_fake.py
Touch when:   the fake gains behaviour — check a real tracker has it too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.intake import client as c
from crb.intake import fake


def _board(path: Path) -> fake.FileTracker:
    path.write_text(
        json.dumps(
            {
                "tickets": {
                    "4711": {
                        "title": "Fix it",
                        "state": "Ready",
                        "revision": "1",
                        "changed": "2026-09-22T09:00:00Z",
                        "tags": ["area:api"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return fake.FileTracker(path)


def test_the_gate_is_off_unless_the_environment_says_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(fake.FAKE_TRACKER_ENV, raising=False)
    assert fake.fake_tracker_enabled() is False
    monkeypatch.setenv(fake.FAKE_TRACKER_ENV, "1")
    assert fake.fake_tracker_enabled() is True
    monkeypatch.setenv(fake.FAKE_TRACKER_ENV, "0")
    assert fake.fake_tracker_enabled() is False


def test_it_satisfies_the_same_protocol_the_real_adapters_do(tmp_path: Path) -> None:
    assert isinstance(fake.FileTracker(tmp_path / "b.json"), c.TrackerClient)


def test_the_column_lists_only_tickets_in_the_watched_state(tmp_path: Path) -> None:
    t = _board(tmp_path / "b.json")
    assert [r.key for r in t.entered("Ready", "")] == ["4711"]
    assert t.entered("Done", "") == []


def test_a_watermark_filters_tickets_that_have_not_moved_since(tmp_path: Path) -> None:
    t = _board(tmp_path / "b.json")
    assert t.entered("Ready", "2026-09-23") == []
    assert [r.key for r in t.entered("Ready", "2026-09-01")] == ["4711"]


def test_a_repeated_comment_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    t = _board(path)
    t.comment("4711", "hello", "<!-- m -->")
    before = path.stat().st_mtime_ns
    t.comment("4711", "hello", "<!-- m -->")
    assert path.stat().st_mtime_ns == before


def test_a_label_replaces_the_products_own_and_leaves_other_peoples_alone(tmp_path: Path) -> None:
    t = _board(tmp_path / "b.json")
    t.label("4711", c.LABEL_NEEDS_INFO)
    t.label("4711", c.LABEL_QUEUED)
    assert t.read("4711").tags == ("area:api", c.LABEL_QUEUED)


def test_a_label_leaves_the_classifier_tags_on_the_board_ticket(tmp_path: Path) -> None:
    """The board behaves as Azure DevOps and Jira do: the state label replaces the other
    three, and ``crb:class=`` (an input to the draft, not a state) stays put. A fake that
    cleared every ``crb:`` tag would let the walkthrough pass over the adapters' bug."""
    path = tmp_path / "b.json"
    t = _board(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["tickets"]["4711"]["tags"] = ["area:api", "crb:class=backend.route.add", "crb:ready"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    t.label("4711", c.LABEL_QUEUED)
    assert t.read("4711").tags == ("area:api", "crb:class=backend.route.add", c.LABEL_QUEUED)


def test_a_workflow_it_was_told_to_refuse_refuses(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    t = _board(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["tickets"]["4711"]["allowed_states"] = ["In progress"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(c.TrackerError) as err:
        t.transition("4711", "Done")
    assert err.value.reason == c.REASON_REFUSED


def test_an_unknown_ticket_is_refused_rather_than_invented(tmp_path: Path) -> None:
    with pytest.raises(c.TrackerError) as err:
        _board(tmp_path / "b.json").read("9999")
    assert err.value.reason == c.REASON_REFUSED


def test_an_unreadable_board_is_reported_as_the_column_being_gone(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(c.TrackerError) as err:
        fake.FileTracker(path).entered("Ready", "")
    assert err.value.reason == c.REASON_COLUMN_GONE


def test_a_link_is_attached_once(tmp_path: Path) -> None:
    t = _board(tmp_path / "b.json")
    t.link("4711", "https://pr/1")
    t.link("4711", "https://pr/1")
    assert t.read("4711").links == ("https://pr/1",)
