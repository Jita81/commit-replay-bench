"""The MCP server's HTTP client for the crb API.

Navigation
----------
What it is:   ``CrbApi`` — a small, synchronous client over ``/api/v1`` that the MCP tools
              call. It logs in with a LOCAL account, carries the session cookie and the CSRF
              double-submit header, retries once on a 401 (session expiry), and turns the
              API's error envelope into ``CrbApiError``.
What it does: Keeps every MCP tool a one-line pass-through: the tool names the path and the
              parameters; the client does auth, CSRF, paging defaults and error shaping.
              Nothing here interprets a verdict — the API's JSON is returned as-is so the
              caller sees exactly what the UI sees (``n``, intervals, apparatus, policy).
How:          ``httpx.Client`` (or any subclass — the tests inject FastAPI's ``TestClient``,
              which is one) with ``base_url`` = ``CRB_API_URL``; ``login()`` POSTs
              ``/auth/login``, then every unsafe request adds ``X-CSRF-Token`` from the
              ``crb_csrf`` cookie (``__Host-crb_csrf`` on a TLS deployment) the way the
              browser does (src/crb/server/app.py's CSRF middleware). Credentials come from the environment (``CRB_MCP_USERNAME`` /
              ``CRB_MCP_PASSWORD``) and are never logged or echoed.
Layer:        mcp — docs/ARCHITECTURE.md#44-outer-layers (a client of the server layer, never
              an importer of it)
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/mcp/server.py (the tools), src/crb/server/routes/auth.py (the login
              route and cookies), src/crb/server/deps.py (the error envelope this decodes),
              docs/MCP.md (how an operator configures it)
Tested by:    tests/test_mcp_server.py (over the real app via ``TestClient``)
Touch when:   the API grows an auth scheme (a bearer token for service accounts — the seam
              is ``login``/``_headers``); never for a new repository.
Claims:       none — a transport; every number it returns is the API's, with the API's
              method fields intact.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
#: Cookie names and the CSRF header are the server's (src/crb/server/auth.py). A deployment
#: with secure cookies names the CSRF cookie ``__Host-crb_csrf``; that name is read first.
CSRF_COOKIE = "crb_csrf"
CSRF_COOKIE_NAMES: tuple[str, ...] = ("__Host-" + CSRF_COOKIE, CSRF_COOKIE)
CSRF_HEADER = "X-CSRF-Token"
#: Paths that must not carry the CSRF header (no session exists before login).
_PRE_AUTH = ("/auth/login",)
#: Unsafe methods carry the double-submit header.
_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CrbApiError(RuntimeError):
    """The API refused: ``status``, the envelope's ``code`` and ``message``, and ``detail``."""

    def __init__(self, status: int, code: str, message: str, detail: Any = None) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        """The shape a tool returns instead of raising — an MCP client sees the API's words."""
        return {
            "error": True,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class CrbApi:
    """A logged-in session against one crb API.

    ``client`` is any ``httpx.Client`` whose ``base_url`` is the API prefix; the tests pass
    FastAPI's ``TestClient`` (an ``httpx.Client``) over the real app. ``username`` /
    ``password`` are a LOCAL account — the MCP server has no browser to complete an OIDC
    round-trip; an organisation that uses OIDC creates one local service account with the
    role the tools need (viewer for a read-only assistant, operator to start runs).
    """

    def __init__(
        self,
        client: httpx.Client,
        *,
        username: str = "",
        password: str = "",
        prefix: str = "",
    ) -> None:
        self.client = client
        self.username = username
        self._password = password
        #: ``TestClient`` has no base_url prefix for the API — callers pass it explicitly.
        self.prefix = prefix
        self.logged_in = False

    # --- construction from the environment ---------------------------------------
    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> CrbApi:
        """``CRB_API_URL`` (default ``http://127.0.0.1:8000/api/v1``), ``CRB_MCP_USERNAME``,
        ``CRB_MCP_PASSWORD``; ``CRB_MCP_TIMEOUT_S`` (default 60)."""
        e = environ if environ is not None else dict(os.environ)
        base = e.get("CRB_API_URL", DEFAULT_API_URL).rstrip("/")
        timeout = float(e.get("CRB_MCP_TIMEOUT_S", "60"))
        client = httpx.Client(base_url=base, timeout=timeout, follow_redirects=False)
        return cls(
            client,
            username=e.get("CRB_MCP_USERNAME", ""),
            password=e.get("CRB_MCP_PASSWORD", ""),
        )

    # --- auth ------------------------------------------------------------------------
    def login(self) -> dict[str, Any]:
        """``POST /auth/login``; returns the principal. Raises ``CrbApiError`` on refusal."""
        if not self.username or not self._password:
            raise CrbApiError(
                401,
                "no_credentials",
                "CRB_MCP_USERNAME and CRB_MCP_PASSWORD are not set — the MCP server needs a "
                "local crb account (see docs/MCP.md)",
            )
        r = self.client.post(
            f"{self.prefix}/auth/login",
            json={"username": self.username, "password": self._password},
        )
        if r.status_code != 200:
            raise _error_of(r)
        self.logged_in = True
        body = r.json()  # the route returns the principal — no second request, no recursion
        return dict(body) if isinstance(body, dict) else {"principal": body}

    def me(self) -> dict[str, Any]:
        """``GET /auth/me`` — who the tools act as (and with which role)."""
        me = self.get("/auth/me")
        return dict(me) if isinstance(me, dict) else {"principal": me}

    def _headers(self, method: str, path: str) -> dict[str, str]:
        if method in _UNSAFE and not path.startswith(_PRE_AUTH):
            for name in CSRF_COOKIE_NAMES:
                token = self.client.cookies.get(name)
                if token:
                    return {CSRF_HEADER: token}
        return {}

    # --- requests --------------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """One request under the prefix; logs in lazily; retries once after a 401 (the
        session cookie expired). Returns the decoded JSON (or the text for non-JSON)."""
        if not self.logged_in:
            self.login()
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        r = self.client.request(
            method,
            f"{self.prefix}{path}",
            params=clean,
            json=json,
            headers=self._headers(method, path),
        )
        if r.status_code == 401:
            self.logged_in = False
            self.login()
            r = self.client.request(
                method,
                f"{self.prefix}{path}",
                params=clean,
                json=json,
                headers=self._headers(method, path),
            )
        if r.status_code >= 400:
            raise _error_of(r)
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            return r.json()
        return r.text

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None, **params: Any) -> Any:
        return self.request("POST", path, params=params, json=json)

    def put(self, path: str, json: Any = None, **params: Any) -> Any:
        return self.request("PUT", path, params=params, json=json)

    def close(self) -> None:
        self.client.close()


def _error_of(r: httpx.Response) -> CrbApiError:
    """The API's ``{"error": {"code", "message", "detail"}}`` envelope, or the bare text."""
    try:
        body = r.json()
    except ValueError:
        return CrbApiError(r.status_code, "http_error", r.text[:500])
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return CrbApiError(
            r.status_code,
            str(err.get("code", "error")),
            str(err.get("message", "")),
            err.get("detail"),
        )
    return CrbApiError(r.status_code, "http_error", str(body)[:500])
