"""A tracker in a file — for the walkthrough and for a demonstration, never for production.

The browser walkthrough has to prove the whole journey: a ticket enters a column, the
product comments on it, a person edits it, the item is queued, the pull request link
lands, the outcome moves the ticket. Doing that against a real Azure DevOps or Jira
would put a credential and somebody's board into CI, so this file is the tracker
instead: one JSON document under ``CRB_HOME`` that a test seeds and then reads back.

It is the same shape as the real thing on purpose — it satisfies
:class:`crb.intake.client.TrackerClient`, so the walkthrough exercises the real service,
the real readiness gate, the real chain and the real screen. Only the six verbs are
faked.

**It cannot be switched on by accident.** ``tracker: fake`` is refused unless
``CRB_ENABLE_FAKE_TRACKER=1`` is set in the environment, exactly as the fixture builder
is gated (``CRB_ENABLE_FIXTURE_BUILDER``). A production deployment that has not set that
variable cannot reach this code at all.

Navigation
----------
What it is:   ``FileTracker`` — a ``TrackerClient`` whose whole board is one JSON file —
              and ``fake_tracker_enabled`` / ``fake_tracker_path``, the gate and the path.
What it does: Lets the walkthrough and a local demonstration drive the entire intake
              journey with no network, no credential and no third-party account, while
              the product's own code runs unchanged.
How:          Reads and writes one document (``{"tickets": {...}, "column": [...]}``)
              under ``<CRB_HOME>/intake-fake.json``; comments are stored by marker so the
              idempotency the real adapters implement is exercised here too.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the protocol it satisfies),
              src/crb/server/intake.py (``build_tracker`` builds it when the gate is on),
              ui/e2e/walkthrough/12-intake.spec.ts (the spec that seeds and reads it),
              scripts/walkthrough.sh (sets ``CRB_ENABLE_FAKE_TRACKER=1``)
Tested by:    tests/test_intake_fake.py
Touch when:   the protocol gains a verb; never to add behaviour a real tracker does not
              have — a fake that is kinder than the real thing proves nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from crb.intake.client import (
    LABEL_PREFIX,
    REASON_COLUMN_GONE,
    REASON_REFUSED,
    Ticket,
    TicketRef,
    TrackerError,
)

#: The environment switch. Without it, ``tracker: fake`` is refused.
FAKE_TRACKER_ENV = "CRB_ENABLE_FAKE_TRACKER"
#: The document's name under ``CRB_HOME``.
FAKE_TRACKER_FILE = "intake-fake.json"


def fake_tracker_enabled(environ: dict[str, str] | None = None) -> bool:
    """``CRB_ENABLE_FAKE_TRACKER=1`` — the only way this tracker can be built."""
    env = os.environ if environ is None else environ
    return str(env.get(FAKE_TRACKER_ENV, "")).strip().lower() in ("1", "true", "yes")


def fake_tracker_path(home: str | Path) -> Path:
    """Where the document lives for a deployment rooted at ``home``."""
    return Path(home).expanduser() / FAKE_TRACKER_FILE


class FileTracker:
    """The six verbs over one JSON document."""

    name = "fake"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # --- the document ---------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"tickets": {}, "column": []}
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise TrackerError(
                REASON_COLUMN_GONE, "the fake tracker's board is unreadable"
            ) from exc

    def _save(self, doc: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)

    def _ticket(self, doc: dict[str, Any], key: str) -> dict[str, Any]:
        got = dict(doc.get("tickets") or {}).get(key)
        if got is None:
            raise TrackerError(REASON_REFUSED, f"no ticket {key!r} on this board")
        return dict(got)

    # --- the six verbs --------------------------------------------------------
    def entered(self, column: str, since: str) -> list[TicketRef]:
        doc = self._load()
        out: list[TicketRef] = []
        for key, raw in sorted(dict(doc.get("tickets") or {}).items()):
            t = dict(raw)
            if str(t.get("state", "")) != column:
                continue
            changed = str(t.get("changed", ""))
            if since and changed and changed < since:
                continue
            out.append(
                TicketRef(
                    key=key,
                    revision=str(t.get("revision", "")),
                    title=str(t.get("title", "")),
                    url=str(t.get("url", "")),
                    changed=changed,
                )
            )
        return out

    def read(self, key: str) -> Ticket:
        return Ticket.from_dict({**self._ticket(self._load(), key), "key": key})

    def comment(self, key: str, text: str, marker: str) -> None:
        doc = self._load()
        t = self._ticket(doc, key)
        comments = dict(t.get("comments") or {})
        if comments.get(marker) == text:
            return
        comments[marker] = text
        t["comments"] = comments
        doc["tickets"][key] = t
        self._save(doc)

    def label(self, key: str, value: str) -> None:
        doc = self._load()
        t = self._ticket(doc, key)
        tags = [x for x in list(t.get("tags") or []) if not str(x).startswith(LABEL_PREFIX)]
        t["tags"] = [*tags, value]
        doc["tickets"][key] = t
        self._save(doc)

    def transition(self, key: str, state: str) -> None:
        doc = self._load()
        t = self._ticket(doc, key)
        allowed = list(t.get("allowed_states") or [])
        if allowed and state not in allowed:
            raise TrackerError(REASON_REFUSED, f"the workflow does not allow {state!r} from here")
        t["state"] = state
        doc["tickets"][key] = t
        self._save(doc)

    def link(self, key: str, url: str) -> None:
        doc = self._load()
        t = self._ticket(doc, key)
        links = list(t.get("links") or [])
        if url not in links:
            t["links"] = [*links, url]
            doc["tickets"][key] = t
            self._save(doc)


__all__ = [
    "FAKE_TRACKER_ENV",
    "FAKE_TRACKER_FILE",
    "FileTracker",
    "fake_tracker_enabled",
    "fake_tracker_path",
]
