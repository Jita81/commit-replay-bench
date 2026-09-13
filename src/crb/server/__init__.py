"""crb.server — the FastAPI surface an operator, approver or UI talks to.

* :mod:`crb.server.settings` — ``CRB_``-prefixed environment settings (secrets never logged).
* :mod:`crb.server.app`      — ``create_app()``: lifespan, middleware, error envelope, router seam.
* :mod:`crb.server.auth`     — local accounts (argon2), OIDC (authlib), signed cookie sessions,
  CSRF double-submit, the ``viewer < operator < approver < admin`` role ladder.
* :mod:`crb.server.deps`     — request-scoped dependencies and shared response models.
* :mod:`crb.server.routes`   — one submodule per resource; each exposes ``router``.
* :mod:`crb.server.main`     — ``serve(host, port)`` for ``crb serve``.

The server never decides a verdict. It reads the ledger, enqueues runs, and enforces
who may do what. Every response that is not a success is the API.md error envelope.
"""

from crb.server.app import create_app, register_routers

__all__ = ["create_app", "register_routers"]
