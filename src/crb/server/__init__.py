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

Navigation
----------
What it is:   The ``crb.server`` package — the FastAPI layer's map and its two public names.
What it does: Re-exports ``create_app`` and ``register_routers``; the docstring above is the
              index of the package's modules and the one rule they share (the server never
              decides a verdict).
How:          Plain re-exports; no logic.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/server/app.py (the factory), src/crb/server/main.py (``crb serve``),
              src/crb/server/routes/__init__.py (the resource modules), src/crb/server/auth.py
              (who may do what), src/crb/server/worker.py (the queue consumer that lives
              beside the API)
Tested by:    tests/test_server_app.py
Touch when:   never for a new repository; only when a new top-level server entry point is
              added (re-export it here and list it in the docstring).
"""

from crb.server.app import create_app, register_routers

__all__ = ["create_app", "register_routers"]
