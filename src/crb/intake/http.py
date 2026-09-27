"""The one HTTP door the tracker adapters use, and the one place their errors get a word.

Both adapters are stdlib plus ``httpx`` and nothing else — no vendor SDK, so nothing
about a tracker's client library can change what this product sends or how it fails.
Everything they share lives here: a request with the right headers, a timeout, and the
translation from "what the tracker did" to one of
:data:`crb.intake.client.STOP_REASONS`.

Three rules the translation keeps:

* **A credential never leaves.** The ``Authorization`` header is built here from a token
  the caller holds; it is never logged, never put in a URL, and never carried into a
  :class:`~crb.intake.client.TrackerError` message. It is sent ONLY to the tracker's own
  origin: a request URL whose scheme, host or port differ from ``base_url``'s is refused
  before anything is sent (assessment 2026-09-25, C6e) — an absolute URL a tracker (or a
  future caller) hands back cannot redirect the token.
* **The tracker's body is not repeated.** A 4xx or 5xx becomes the product's own
  sentence, because a tracker's error body can contain project data and, in a hosted
  deployment, is not ours to show.
* **A rate limit is waited out, briefly.** HTTP 429 honours ``Retry-After`` (seconds or
  an HTTP date), never waiting longer than :data:`MAX_RETRY_WAIT_S` per try nor more than
  :data:`MAX_RETRIES` times; with no header the wait doubles from one second. Only then is
  it ``unreachable`` (C6d) — a pass holding an API request cannot wait for minutes.

Navigation
----------
What it is:   ``TrackerHttp`` — a thin, injectable ``httpx.Client`` wrapper shared by the
              Azure DevOps and Jira adapters.
What it does: Sends JSON requests with basic authentication to the tracker's own origin
              only (another origin is refused), applies one timeout, waits out a 429 within
              a cap, and maps every transport failure and every non-2xx status onto a
              ``TrackerError`` with one of the published stop reasons.
How:          ``httpx.Client`` is injected (a test passes a ``MockTransport``; nothing in
              the suite or in CI ever reaches a real tracker) and so is ``sleep``; the URL is
              resolved and its origin compared with ``base_url``'s before the header is
              built; the status map is a table, not a chain of ifs, so a reader can see
              every case at once.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/client.py (the ``TrackerError`` and its reason words),
              src/crb/intake/ado.py and src/crb/intake/jira.py (the two callers),
              src/crb/server/github_app.py (the same shape for the GitHub App)
Tested by:    tests/test_intake_adapters.py
Touch when:   a tracker needs an auth scheme other than basic (add it here, not in an
              adapter); a status needs a different reason word.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from crb.intake.client import (
    REASON_COLUMN_GONE,
    REASON_REFUSED,
    REASON_UNAUTHORISED,
    REASON_UNREACHABLE,
    TrackerError,
)

#: Seconds any one tracker call may take. A poll that hangs would hold the worker's idle
#: loop, so this is deliberately short.
DEFAULT_TIMEOUT_S = 20.0

#: HTTP status → the stop reason the listener records. Anything not named here is
#: ``refused`` (the tracker answered and said no).
STATUS_REASON: dict[int, str] = {
    401: REASON_UNAUTHORISED,
    403: REASON_UNAUTHORISED,
    404: REASON_COLUMN_GONE,
    408: REASON_UNREACHABLE,
    429: REASON_UNREACHABLE,
    500: REASON_UNREACHABLE,
    502: REASON_UNREACHABLE,
    503: REASON_UNREACHABLE,
    504: REASON_UNREACHABLE,
}


#: How many times a 429 is retried before the call is ``unreachable``.
MAX_RETRIES = 2
#: The longest one wait for a 429 may be, whatever ``Retry-After`` asks for: a pass runs in
#: the worker's idle loop and inside an API request, under a budget of its own.
MAX_RETRY_WAIT_S = 10.0


def retry_after_seconds(value: str) -> float | None:
    """``Retry-After`` as seconds (RFC 9110: a non-negative integer, or an HTTP date);
    ``None`` when it is absent or cannot be read. A date in the past is ``0``."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        return max(0.0, float(int(v)))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _origin(url: str) -> tuple[str, str, int | None]:
    """``(scheme, host, port)`` with the scheme's default port made explicit, so
    ``https://x`` and ``https://x:443`` are one origin."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    port = parts.port or {"https": 443, "http": 80}.get(scheme)
    return scheme, (parts.hostname or "").lower(), port


def basic_auth(user: str, token: str) -> str:
    """``Basic <base64(user:token)>``. Azure DevOps wants an empty user with a PAT; Jira
    wants the account's email address with an API token."""
    raw = f"{user}:{token}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


class TrackerHttp:
    """JSON over HTTP for one tracker, with one timeout and one error vocabulary."""

    def __init__(
        self,
        base_url: str,
        authorization: str,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("a tracker needs a base URL")
        self.base_url = base_url.rstrip("/")
        self._authorization = authorization
        self.client = client or httpx.Client(timeout=timeout_s)
        self.timeout_s = timeout_s
        self._sleep = sleep
        self._origin = _origin(self.base_url)

    def _resolve(self, path: str) -> str:
        """The absolute URL for ``path`` — relative to ``base_url``, or ``path`` itself when
        it is absolute AND on the tracker's own origin. Any other origin is refused: the
        credential this client holds is for the tracker, and only the tracker."""
        if "://" not in path:
            return f"{self.base_url}/{path.lstrip('/')}"
        if _origin(path) != self._origin:
            raise TrackerError(
                REASON_REFUSED,
                "refused a request to another origin than the tracker's own "
                f"({_origin(path)[0]}://{_origin(path)[1]}): the credential is sent only "
                "to the configured tracker",
            )
        return path

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content_type: str = "application/json",
        expect: tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        """One call. Returns the decoded body (``None`` for 204 or an empty body).

        ``path`` is appended to ``base_url`` when it is relative, and used as-is when it is
        an absolute URL on the tracker's own origin — any other origin is refused before
        the credential is attached. A 429 is retried after ``Retry-After`` (capped).
        """
        url = self._resolve(path)
        headers = {
            "Authorization": self._authorization,
            "Accept": "application/json",
            "Content-Type": content_type,
        }
        attempt = 0
        while True:
            try:
                r = self.client.request(
                    method, url, params=dict(params or {}), json=json, headers=headers
                )
            except httpx.HTTPError as exc:
                raise TrackerError(
                    REASON_UNREACHABLE, f"{type(exc).__name__} calling the tracker"
                ) from exc
            if r.status_code != 429 or 429 in expect:
                break
            if attempt >= MAX_RETRIES:
                raise TrackerError(
                    REASON_UNREACHABLE,
                    f"the tracker is rate limiting this product (429 for {method} "
                    f"{_safe_path(url)}) after {attempt} wait(s); the next pass tries again",
                )
            asked = retry_after_seconds(r.headers.get("Retry-After", ""))
            wait = float(2**attempt) if asked is None else asked
            self._sleep(min(wait, MAX_RETRY_WAIT_S))
            attempt += 1
        if r.status_code not in expect:
            reason = STATUS_REASON.get(r.status_code, REASON_REFUSED)
            raise TrackerError(
                reason,
                f"the tracker answered {r.status_code} for {method} {_safe_path(url)}",
            )
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError as exc:
            raise TrackerError(REASON_REFUSED, "the tracker's answer was not JSON") from exc

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        return self.request("PUT", path, **kw)


def _safe_path(url: str) -> str:
    """The path of a URL without its query string — a query can carry a ticket's words."""
    return url.split("?", 1)[0]


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "MAX_RETRIES",
    "MAX_RETRY_WAIT_S",
    "STATUS_REASON",
    "TrackerHttp",
    "basic_auth",
    "retry_after_seconds",
]
