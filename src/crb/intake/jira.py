"""Jira as a tracker: the same six verbs over JQL and the issue REST API.

Jira is the second tracker, and it is deliberately the same shape as the first: if this
file needed a concept Azure DevOps does not have, the protocol would be wrong. Three
things genuinely differ, and each is handled in one place:

* **The body is ADF, not HTML.** :func:`crb.intake.draft.adf_to_text` flattens it.
  Comments must be *written* as ADF too, so :func:`text_to_adf` turns the renderer's
  plain lines back into a document — the marker survives as ordinary text.
* **A status is not a field you set.** Jira moves an issue through a *transition*, so
  :meth:`JiraTracker.transition` reads the transitions available on this issue and uses
  the one that lands on the wanted status. No such transition is a refusal, never a
  force.
* **Story points live in a custom field.** Its id differs per site, so it is
  configuration (``points_field``), and an unconfigured site simply has no estimate —
  the draft then says the size is a default.

Navigation
----------
What it is:   ``JiraTracker`` — the :class:`crb.intake.client.TrackerClient` over Jira
              Cloud — with ``JiraConfig`` and the ADF converter ``text_to_adf``.
What it does: Runs the JQL search for the watched status, reads an issue's fields, leaves
              ONE comment idempotent by its marker, replaces the ``crb:`` label, moves
              the status through a real transition and attaches a remote link.
How:          ``TrackerHttp`` (httpx, injectable) against ``/rest/api/3/*``; an account
              email plus an API token as basic auth.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the protocol it satisfies),
              src/crb/intake/http.py (the request and the error vocabulary),
              src/crb/intake/draft.py (``adf_to_text``), src/crb/intake/ado.py (the same
              six verbs over WIQL), src/crb/server/intake.py (builds it from settings)
Tested by:    tests/test_intake_adapters.py
Touch when:   Atlassian moves the search route again (it has), or a site needs a second
              custom field read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from crb.intake.client import (
    LABEL_PREFIX,
    REASON_REFUSED,
    Ticket,
    TicketRef,
    TrackerError,
)
from crb.intake.draft import adf_to_text
from crb.intake.http import DEFAULT_TIMEOUT_S, TrackerHttp, basic_auth

API = "rest/api/3"

#: Fields the search and the read ask for by name. Anything else on the issue is not read.
BASE_FIELDS = ("summary", "description", "issuetype", "labels", "status", "updated")


@dataclass(frozen=True)
class JiraConfig:
    """One Jira Cloud connection. No secret: the token is handed to the constructor."""

    #: ``https://<site>.atlassian.net``.
    site_url: str
    project: str
    #: The status the listener watches ("Ready for manufacture").
    column: str
    #: The account the API token belongs to — Jira's basic auth is ``email:token``.
    email: str = ""
    #: Extra JQL ANDed onto the query, for a site that needs a component or a label filter.
    jql: str = ""
    #: The custom field holding story points on this site (``customfield_10016`` is the
    #: usual Jira Software default). Empty means the site has no estimate to read.
    points_field: str = ""
    #: The custom field holding acceptance criteria, where a site has one.
    acceptance_field: str = ""

    def __post_init__(self) -> None:
        for name in ("site_url", "project", "column"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"a Jira connection needs {name}")

    @property
    def base_url(self) -> str:
        return self.site_url.rstrip("/")

    @property
    def fields(self) -> tuple[str, ...]:
        extra = tuple(f for f in (self.points_field, self.acceptance_field) if f)
        return (*BASE_FIELDS, *extra)


def _quote(value: str) -> str:
    """A JQL string literal: double quotes escaped, nothing else interpolated."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def text_to_adf(text: str) -> dict[str, Any]:
    """Plain lines → an ADF document of one paragraph per line.

    Jira Cloud's comment API takes ADF and nothing else. The renderer's Markdown is not
    converted to rich text — it is carried as text, so what a person reads on the issue
    is exactly what the product wrote, marker included.
    """
    lines = text.splitlines() or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": ([{"type": "text", "text": ln}] if ln else []),
            }
            for ln in lines
        ],
    }


class JiraTracker:
    """Jira behind the six verbs."""

    name = "jira"

    def __init__(
        self,
        config: JiraConfig,
        token: str,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.config = config
        self.http = TrackerHttp(
            config.base_url,
            basic_auth(config.email, token),
            client=client,
            timeout_s=timeout_s,
        )

    # --- read ---------------------------------------------------------------------
    def entered(self, column: str, since: str) -> list[TicketRef]:
        clauses = [
            f"project = {_quote(self.config.project)}",
            f"status = {_quote(column)}",
        ]
        if since:
            clauses.append(f"updated >= {_quote(since)}")
        if self.config.jql:
            clauses.append(f"({self.config.jql})")
        jql = " AND ".join(clauses) + " ORDER BY updated ASC"
        body = self.http.post(
            f"{API}/search/jql",
            json={"jql": jql, "fields": list(BASE_FIELDS), "maxResults": 200},
            expect=(200,),
        )
        out: list[TicketRef] = []
        for issue in (body or {}).get("issues", []):
            fields = issue.get("fields") or {}
            out.append(
                TicketRef(
                    key=str(issue.get("key", "")),
                    revision=str(fields.get("updated", "")),
                    title=str(fields.get("summary", "")),
                    url=self._web_url(str(issue.get("key", ""))),
                    changed=str(fields.get("updated", "")),
                )
            )
        return out

    def _web_url(self, key: str) -> str:
        return f"{self.config.base_url}/browse/{key}"

    def read(self, key: str) -> Ticket:
        issue = self.http.get(
            f"{API}/issue/{key}",
            params={"fields": ",".join(self.config.fields)},
            expect=(200,),
        )
        fields = (issue or {}).get("fields") or {}
        points = fields.get(self.config.points_field) if self.config.points_field else None
        criteria_raw = (
            fields.get(self.config.acceptance_field) if self.config.acceptance_field else None
        )
        criteria = (
            tuple(ln for ln in adf_to_text(criteria_raw).splitlines() if ln.strip())
            if criteria_raw
            else ()
        )
        status = (fields.get("status") or {}).get("name", "")
        issue_type = (fields.get("issuetype") or {}).get("name", "")
        return Ticket(
            key=str(key),
            title=str(fields.get("summary", "")),
            body=adf_to_text(fields.get("description")),
            acceptance_criteria=criteria,
            type=str(issue_type),
            tags=tuple(str(x) for x in (fields.get("labels") or [])),
            points=None if points in (None, "") else float(points),
            revision=str(fields.get("updated", "")),
            url=self._web_url(str(key)),
            state=str(status),
        )

    # --- write --------------------------------------------------------------------
    def comment(self, key: str, text: str, marker: str) -> None:
        body = self.http.get(
            f"{API}/issue/{key}/comment", params={"maxResults": 200}, expect=(200,)
        )
        for c in (body or {}).get("comments", []):
            existing = adf_to_text(c.get("body"))
            if marker not in existing:
                continue
            if existing.strip() == text.strip():
                return
            self.http.put(
                f"{API}/issue/{key}/comment/{c.get('id')}",
                json={"body": text_to_adf(text)},
                expect=(200,),
            )
            return
        self.http.post(
            f"{API}/issue/{key}/comment", json={"body": text_to_adf(text)}, expect=(201,)
        )

    def label(self, key: str, value: str) -> None:
        """Set one ``crb:`` label, removing any other. Jira labels may not contain a
        space, which every label in :data:`crb.intake.client.LABELS` respects."""
        current = self.read(key).tags
        remove = [t for t in current if t.lower().startswith(LABEL_PREFIX) and t != value]
        if value in current and not remove:
            return
        updates = [{"remove": t} for t in remove]
        if value not in current:
            updates.append({"add": value})
        self.http.put(f"{API}/issue/{key}", json={"update": {"labels": updates}}, expect=(204,))

    def transition(self, key: str, state: str) -> None:
        """Move the issue by the transition that lands on ``state``. No such transition
        from where the issue is now is a refusal — the product never forces a workflow."""
        body = self.http.get(f"{API}/issue/{key}/transitions", expect=(200,))
        for t in (body or {}).get("transitions", []):
            to_name = str((t.get("to") or {}).get("name", ""))
            if to_name.casefold() == state.casefold():
                self.http.post(
                    f"{API}/issue/{key}/transitions",
                    json={"transition": {"id": str(t.get("id"))}},
                    expect=(204,),
                )
                return
        raise TrackerError(
            REASON_REFUSED,
            f"the workflow offers no transition to {state!r} from where this issue is now",
        )

    def link(self, key: str, url: str) -> None:
        """Attach a remote link once. Jira's remote-link API is idempotent on
        ``globalId``, so the URL itself is the identity."""
        self.http.post(
            f"{API}/issue/{key}/remotelink",
            json={"globalId": url, "object": {"url": url, "title": "Pull request"}},
            expect=(200, 201),
        )


__all__ = ["API", "BASE_FIELDS", "JiraConfig", "JiraTracker", "text_to_adf"]
