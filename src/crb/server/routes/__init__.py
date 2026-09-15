"""crb.server.routes — one submodule per resource.

Contract with :func:`crb.server.app.register_routers`: a submodule that exposes a
module-level ``router: fastapi.APIRouter`` is mounted under ``/api/v1`` (so declare
paths relative to that: ``@router.get("/repos")``). Modules are mounted in sorted
name order; a module without ``router`` is ignored; a module that fails to import
stops the server from starting.

Core (W2-A): ``auth``, ``system``, ``admin``. Domain resources (repos, runs, grades,
capability, routes, forecast, signoffs, ledger, oracle, factory) are added by W2-B.

Navigation
----------
What it is:   The routes package — the contract every resource module follows to be mounted.
What it does: Documents the ``router`` convention ``register_routers`` relies on: expose a
              module-level ``APIRouter``, declare paths relative to ``/api/v1``, and know
              that an import error stops the server rather than silently dropping a
              resource.
How:          Packaging only; discovery is ``pkgutil.iter_modules`` in sorted name order.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/app.py (``register_routers``), src/crb/server/routes/system.py
              (health / metrics / version), src/crb/server/routes/auth.py (login and
              sessions), src/crb/server/routes/runs.py (the queue over HTTP),
              src/crb/server/routes/signoffs.py (the 409 gate), docs/API.md (the contract
              the modules implement)
Tested by:    tests/test_server_app.py
Touch when:   a new resource is added — create a module here with a ``router``, add its
              section to docs/API.md, and a matching test module (one per resource, as in
              tests/test_server_routes_repos.py).
"""
