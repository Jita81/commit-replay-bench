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

import re
from dataclasses import dataclass
from typing import Any

import httpx

from crb.intake.client import (
    LINK_ITEM,
    REASON_REFUSED,
    Ticket,
    TicketRef,
    TrackerError,
    is_state_label,
    marker_token,
)
from crb.intake.draft import adf_to_text
from crb.intake.http import DEFAULT_TIMEOUT_S, TrackerHttp, basic_auth

API = "rest/api/3"

#: Fields the search and the read ask for by name. Anything else on the issue is not read.
BASE_FIELDS = ("summary", "description", "issuetype", "labels", "status", "updated")

#: Issues per page of the search. The bound on the whole read is ``JiraConfig.max_refs``;
#: this is only how many pages it takes.
PAGE_SIZE = 100


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
    #: The most issues one read of the column may return, across as many pages as it takes.
    #: The service asks for one MORE than the deployment's ``max_per_poll`` deliberately: it
    #: can then see that the column overflowed and stop the pass with ``column_too_large``
    #: rather than read a truncated column and say nothing (the first version asked for a
    #: single page of 200 and silently ignored the rest).
    max_refs: int = 201

    def __post_init__(self) -> None:
        for name in ("site_url", "project", "column"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"a Jira connection needs {name}")
        if int(self.max_refs) < 1:
            raise ValueError("a Jira connection needs max_refs of at least 1")

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


#: The sentence that carries the marker on a Jira issue. ADF has no hidden node, so the
#: identity is shown rather than smuggled: one line, in plain English, saying who wrote the
#: comment and what its reference is. :func:`crb.intake.client.marker_token` is inside it, so
#: the same lookup finds it as finds Azure DevOps's HTML comment.
ATTRIBUTION = (
    "Posted by Commit Replay Bench — it only ever edits this one comment. Reference: {token}"
)

_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")


def _inline_nodes(text: str) -> list[dict[str, Any]]:
    """One line of the renderer's Markdown as ADF text nodes with marks.

    Only the two marks the renderer actually produces are read — ``**strong**`` and a
    backticked ``code`` span — because a converter that guessed at more would silently eat
    a character a ticket meant literally. Everything else is text.
    """
    out: list[dict[str, Any]] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append({"type": "text", "text": text[pos : m.start()]})
        if m.group(1) is not None:
            out.append({"type": "text", "text": m.group(1), "marks": [{"type": "strong"}]})
        else:
            out.append({"type": "text", "text": m.group(2), "marks": [{"type": "code"}]})
        pos = m.end()
    if pos < len(text):
        out.append({"type": "text", "text": text[pos:]})
    return [n for n in out if n["text"]]


def _paragraph(line: str, *, marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    content = _inline_nodes(line)
    if marks:
        for node in content:
            node["marks"] = [*node.get("marks", []), *marks]
    return {"type": "paragraph", "content": content}


def text_to_adf(text: str, *, footer: str = "") -> dict[str, Any]:
    """The renderer's lines → an ADF document with the structure those lines describe.

    Jira Cloud's comment API takes ADF and nothing else, and an ADF text node is escaped
    content: a Markdown string posted as text reads on the issue as ``## Commit Replay
    Bench``, which is how this adapter first shipped. So the four shapes the renderer
    actually produces are mapped — ``## heading``, ``**strong**``, ``- bullet`` (with the
    indented ``slot:`` line kept inside the same bullet) and a backticked code span — and
    nothing else is guessed at.

    ``footer`` becomes a last, italic paragraph. On Jira that is where the marker lives
    (:data:`ATTRIBUTION`), because ADF cannot hide one.
    """
    content: list[dict[str, Any]] = []
    bullets: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal bullets
        if bullets:
            content.append({"type": "bulletList", "content": bullets})
            bullets = []

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("- "):
            bullets.append({"type": "listItem", "content": [_paragraph(line[2:].strip())]})
            continue
        if bullets and raw.startswith("  "):
            bullets[-1]["content"].append(_paragraph(line.strip()))
            continue
        flush()
        if line.startswith("## "):
            content.append(
                {"type": "heading", "attrs": {"level": 2}, "content": _inline_nodes(line[3:])}
            )
            continue
        content.append(_paragraph(line))
    flush()
    if footer:
        content.append(_paragraph(footer, marks=[{"type": "em"}]))
    if not content:
        content.append({"type": "paragraph", "content": []})
    return {"type": "doc", "version": 1, "content": content}


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
        out: list[TicketRef] = []
        limit = int(self.config.max_refs)
        token = ""
        # paginated until the bound is reached, never one page and silence: Jira's search
        # returns a page plus a `nextPageToken`, and the first version of this adapter asked
        # for 200 and dropped whatever came after them without a word.
        while len(out) < limit:
            payload: dict[str, Any] = {
                "jql": jql,
                "fields": list(BASE_FIELDS),
                "maxResults": min(PAGE_SIZE, limit - len(out)),
            }
            if token:
                payload["nextPageToken"] = token
            body = self.http.post(f"{API}/search/jql", json=payload, expect=(200,))
            issues = (body or {}).get("issues", []) or []
            for issue in issues:
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
            token = str((body or {}).get("nextPageToken") or "")
            if not token or not issues:
                break
        return out[:limit]

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
    def _document(self, text: str, marker: str) -> dict[str, Any]:
        """The ADF this adapter posts: the body with the marker line taken out of it, and
        the marker carried in the attribution footer instead."""
        token = marker_token(marker)
        body = "\n".join(ln for ln in text.splitlines() if marker_token(ln) != token)
        return text_to_adf(body, footer=ATTRIBUTION.format(token=token))

    def comment(self, key: str, text: str, marker: str) -> None:
        """One comment per marker: add it, or edit the one already carrying the marker.

        Identical text writes nothing at all, so a poll that runs every minute does not
        touch the issue between edits. **Both sides of that comparison go through
        ``adf_to_text``**: the round trip is lossy (it drops blank lines), so comparing the
        text the product holds against the flattened text Jira returns would never be equal
        for a real comment, and every poll would rewrite it. Comparing two flattened
        documents is equal exactly when the comment says the same thing.
        """
        token = marker_token(marker)
        doc = self._document(text, marker)
        wanted = adf_to_text(doc).strip()
        body = self.http.get(
            f"{API}/issue/{key}/comment", params={"maxResults": 200}, expect=(200,)
        )
        for c in (body or {}).get("comments", []):
            existing = adf_to_text(c.get("body"))
            if token not in existing:
                continue
            if existing.strip() == wanted:
                return
            self.http.put(
                f"{API}/issue/{key}/comment/{c.get('id')}",
                json={"body": doc},
                expect=(200,),
            )
            return
        self.http.post(f"{API}/issue/{key}/comment", json={"body": doc}, expect=(201,))

    def label(self, key: str, value: str) -> None:
        """Set the product's one STATE label, removing the other three. Jira labels may not
        contain a space, which every label in :data:`crb.intake.client.LABELS` respects.

        A ``crb:`` label that is not one of the four is a classifier tag somebody put on the
        issue (``crb:class=``, ``crb:kind=``, ``crb:level=``) and is left alone: removing it
        by prefix deleted the operator's own classification, and because Jira's
        ``fields.updated`` is the ticket revision, the next draft read the issue without it.
        """
        current = self.read(key).tags
        remove = [t for t in current if is_state_label(t) and t != value]
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

    def link(self, key: str, url: str, title: str = "") -> None:
        """Attach a remote link once, under the name the caller gave it. Jira's remote-link
        API is idempotent on ``globalId``, so the URL itself is the identity.

        The title matters here in a way it does not on Azure DevOps: Jira shows it as the
        link's text. The same verb attaches the backlog item when a ticket is queued and the
        pull request when one opens, so a hard-coded "Pull request" labelled the queued link
        as something that did not exist yet.
        """
        self.http.post(
            f"{API}/issue/{key}/remotelink",
            json={"globalId": url, "object": {"url": url, "title": title or LINK_ITEM}},
            expect=(200, 201),
        )


__all__ = [
    "API",
    "ATTRIBUTION",
    "BASE_FIELDS",
    "PAGE_SIZE",
    "JiraConfig",
    "JiraTracker",
    "text_to_adf",
]
