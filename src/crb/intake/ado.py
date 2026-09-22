"""Azure DevOps as a tracker: a board column watched, and six verbs against it.

Boards Azure DevOps calls *states* (``System.State``) and people call *columns*; this
adapter watches the state, because that is what a work item actually carries and what
a WIQL query can ask for. A team that uses split board columns points the listener at
the state those columns belong to.

The five fields the draft needs, and where they come from:

==========================  =========================================================
``System.Title``            the item's title
``System.Description``      the description (rich-text HTML → plain lines)
``Microsoft.VSTS.Common.``  ``AcceptanceCriteria`` — one line each, HTML → plain lines
``Microsoft.VSTS.``         ``Scheduling.StoryPoints`` — the size estimate
``System.Tags``             semicolon-separated; the product's own ``crb:`` label lives
                            here and is replaced, never appended to
==========================  =========================================================

Every write is one PATCH of a JSON Patch document against exactly one field, or one
comment. Nothing else on the work item is ever touched: the non-goals of
docs/dod/journeys/intake-from-a-ticket.md are visible in the size of this file.

Navigation
----------
What it is:   ``AdoTracker`` — the :class:`crb.intake.client.TrackerClient` over Azure
              DevOps Services or Server, and ``AdoConfig``, the connection it needs.
What it does: Runs the WIQL query for the watched state inside an area path, reads a work
              item's fields, leaves ONE comment idempotent by an HTML marker, replaces the
              ``crb:`` tag, moves the state and attaches a hyperlink.
How:          ``TrackerHttp`` (httpx, injectable) against ``/_apis/wit/*`` at
              ``api-version=7.1``; a personal access token as basic auth with an empty
              user name; HTML is converted by :func:`crb.intake.draft.html_to_text`.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the protocol it satisfies),
              src/crb/intake/http.py (the request and the error vocabulary),
              src/crb/intake/draft.py (``html_to_text``), src/crb/intake/jira.py (the same
              six verbs over JQL), src/crb/server/intake.py (builds it from settings and
              the stored credential)
Tested by:    tests/test_intake_adapters.py
Touch when:   Azure DevOps changes an api-version or a field name; a deployment needs a
              board *column* rather than a state (that is a second query, not an edit here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from crb.intake.client import (
    LABEL_PREFIX,
    REASON_COLUMN_GONE,
    REASON_REFUSED,
    Ticket,
    TicketRef,
    TrackerError,
)
from crb.intake.draft import html_to_text
from crb.intake.http import DEFAULT_TIMEOUT_S, TrackerHttp, basic_auth

#: The API version every call names. Pinned: an unpinned Azure DevOps call takes whatever
#: the service currently defaults to, which is not a contract.
API_VERSION = "7.1"
#: Comments live on a preview route of their own; Microsoft has not promoted it.
COMMENTS_API_VERSION = "7.1-preview.4"

FIELD_TITLE = "System.Title"
FIELD_DESCRIPTION = "System.Description"
FIELD_STATE = "System.State"
FIELD_TAGS = "System.Tags"
FIELD_TYPE = "System.WorkItemType"
FIELD_REV = "System.Rev"
FIELD_CHANGED = "System.ChangedDate"
FIELD_AC = "Microsoft.VSTS.Common.AcceptanceCriteria"
FIELD_POINTS = "Microsoft.VSTS.Scheduling.StoryPoints"

#: What the WIQL query asks for. Everything else comes from the work-item read.
_WIQL_FIELDS = (FIELD_TITLE, FIELD_REV, FIELD_CHANGED)


@dataclass(frozen=True)
class AdoConfig:
    """One Azure DevOps connection. No secret: the token is handed to the constructor."""

    #: ``https://dev.azure.com/<organisation>`` (or a Server collection URL).
    organisation_url: str
    project: str
    #: The ``System.State`` the listener watches ("Ready for manufacture").
    column: str
    #: Optional ``System.AreaPath`` the query is restricted to, so one deployment can
    #: watch one team's board inside a shared project.
    area_path: str = ""

    def __post_init__(self) -> None:
        for name in ("organisation_url", "project", "column"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"an Azure DevOps connection needs {name}")

    @property
    def base_url(self) -> str:
        return f"{self.organisation_url.rstrip('/')}/{self.project}"


def _quote(value: str) -> str:
    """A WIQL string literal. Single quotes are doubled; nothing else is interpolated."""
    return "'" + str(value).replace("'", "''") + "'"


class AdoTracker:
    """Azure DevOps behind the six verbs."""

    name = "ado"

    def __init__(
        self,
        config: AdoConfig,
        token: str,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.config = config
        self.http = TrackerHttp(
            config.base_url,
            basic_auth("", token),
            client=client,
            timeout_s=timeout_s,
        )

    # --- read ---------------------------------------------------------------------
    def entered(self, column: str, since: str) -> list[TicketRef]:
        """Work items whose state is ``column`` and which changed at or after ``since``."""
        clauses = [
            f"[System.TeamProject] = {_quote(self.config.project)}",
            f"[{FIELD_STATE}] = {_quote(column)}",
        ]
        if self.config.area_path:
            clauses.append(f"[System.AreaPath] UNDER {_quote(self.config.area_path)}")
        if since:
            clauses.append(f"[{FIELD_CHANGED}] >= {_quote(since)}")
        # WIQL is not SQL and this is not a database: every value in the query goes
        # through ``_quote`` (single quotes doubled) and the only clauses that exist are
        # the four written above. Nothing a ticket contains reaches this string.
        wiql = (
            "SELECT [System.Id] FROM WorkItems WHERE "  # noqa: S608 — WIQL, and every literal is quoted above
            + " AND ".join(clauses)
            + f" ORDER BY [{FIELD_CHANGED}] ASC"
        )
        body = self.http.post(
            "_apis/wit/wiql",
            params={"api-version": API_VERSION},
            json={"query": wiql},
            expect=(200,),
        )
        ids = [str(w.get("id")) for w in (body or {}).get("workItems", []) if w.get("id")]
        if not ids:
            return []
        return self._refs(ids)

    def _refs(self, ids: list[str]) -> list[TicketRef]:
        """The listing fields for a batch of ids (Azure DevOps caps a batch at 200)."""
        out: list[TicketRef] = []
        for start in range(0, len(ids), 200):
            batch = ids[start : start + 200]
            body = self.http.get(
                "_apis/wit/workitems",
                params={
                    "ids": ",".join(batch),
                    "fields": ",".join(_WIQL_FIELDS),
                    "api-version": API_VERSION,
                },
                expect=(200,),
            )
            for wi in (body or {}).get("value", []):
                fields = wi.get("fields") or {}
                out.append(
                    TicketRef(
                        key=str(wi.get("id")),
                        revision=str(fields.get(FIELD_REV, wi.get("rev", ""))),
                        title=str(fields.get(FIELD_TITLE, "")),
                        url=self._web_url(str(wi.get("id"))),
                        changed=str(fields.get(FIELD_CHANGED, "")),
                    )
                )
        return out

    def _web_url(self, key: str) -> str:
        return f"{self.config.base_url}/_workitems/edit/{key}"

    def read(self, key: str) -> Ticket:
        wi = self.http.get(
            f"_apis/wit/workitems/{key}",
            params={"api-version": API_VERSION, "$expand": "relations"},
            expect=(200,),
        )
        fields = (wi or {}).get("fields") or {}
        tags = tuple(t.strip() for t in str(fields.get(FIELD_TAGS, "")).split(";") if t.strip())
        criteria = tuple(
            ln for ln in html_to_text(str(fields.get(FIELD_AC, ""))).splitlines() if ln.strip()
        )
        points = fields.get(FIELD_POINTS)
        links = tuple(
            str(rel.get("url", ""))
            for rel in ((wi or {}).get("relations") or [])
            if str(rel.get("rel", "")) == "Hyperlink" and rel.get("url")
        )
        return Ticket(
            key=str(key),
            title=str(fields.get(FIELD_TITLE, "")),
            body=html_to_text(str(fields.get(FIELD_DESCRIPTION, ""))),
            acceptance_criteria=criteria,
            type=str(fields.get(FIELD_TYPE, "")),
            tags=tags,
            points=None if points in (None, "") else float(points),
            revision=str(fields.get(FIELD_REV, (wi or {}).get("rev", ""))),
            links=links,
            url=self._web_url(str(key)),
            state=str(fields.get(FIELD_STATE, "")),
        )

    # --- write --------------------------------------------------------------------
    def comment(self, key: str, text: str, marker: str) -> None:
        """One comment per marker: add it, or edit the one already carrying the marker.

        Identical text writes nothing at all, so a poll that runs every minute does not
        touch the ticket between edits.
        """
        body = self.http.get(
            f"_apis/wit/workItems/{key}/comments",
            params={"api-version": COMMENTS_API_VERSION, "$top": 200},
            expect=(200,),
        )
        for c in (body or {}).get("comments", []):
            existing = str(c.get("text", ""))
            if marker not in existing:
                continue
            if existing.strip() == text.strip():
                return
            self.http.patch(
                f"_apis/wit/workItems/{key}/comments/{c.get('id')}",
                params={"api-version": COMMENTS_API_VERSION},
                json={"text": text},
                expect=(200,),
            )
            return
        self.http.post(
            f"_apis/wit/workItems/{key}/comments",
            params={"api-version": COMMENTS_API_VERSION},
            json={"text": text},
            expect=(200, 201),
        )

    def _patch(self, key: str, operations: list[dict[str, Any]]) -> None:
        self.http.patch(
            f"_apis/wit/workitems/{key}",
            params={"api-version": API_VERSION},
            json=operations,
            content_type="application/json-patch+json",
            expect=(200,),
        )

    def label(self, key: str, value: str) -> None:
        """Set one ``crb:`` tag, removing any other. Other teams' tags are left alone."""
        current = self.read(key).tags
        kept = [t for t in current if not t.lower().startswith(LABEL_PREFIX)]
        wanted = [*kept, value]
        if list(current) == wanted:
            return
        self._patch(
            key, [{"op": "add", "path": f"/fields/{FIELD_TAGS}", "value": "; ".join(wanted)}]
        )

    def transition(self, key: str, state: str) -> None:
        """Move the work item's state. A workflow that forbids the move is a refusal, and
        the product never retries it with a different state."""
        try:
            self._patch(key, [{"op": "add", "path": f"/fields/{FIELD_STATE}", "value": state}])
        except TrackerError as exc:
            if exc.reason == REASON_COLUMN_GONE:
                raise TrackerError(
                    REASON_REFUSED,
                    f"the board has no state {state!r} for this work item type",
                ) from exc
            raise

    def link(self, key: str, url: str) -> None:
        """Attach a hyperlink once; a second call with the same URL writes nothing."""
        if url in self.read(key).links:
            return
        self._patch(
            key,
            [{"op": "add", "path": "/relations/-", "value": {"rel": "Hyperlink", "url": url}}],
        )


__all__ = [
    "API_VERSION",
    "COMMENTS_API_VERSION",
    "FIELD_AC",
    "FIELD_POINTS",
    "FIELD_STATE",
    "FIELD_TAGS",
    "AdoConfig",
    "AdoTracker",
]
