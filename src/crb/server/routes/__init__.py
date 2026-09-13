"""crb.server.routes — one submodule per resource.

Contract with :func:`crb.server.app.register_routers`: a submodule that exposes a
module-level ``router: fastapi.APIRouter`` is mounted under ``/api/v1`` (so declare
paths relative to that: ``@router.get("/repos")``). Modules are mounted in sorted
name order; a module without ``router`` is ignored; a module that fails to import
stops the server from starting.

Core (W2-A): ``auth``, ``system``, ``admin``. Domain resources (repos, runs, grades,
capability, routes, forecast, signoffs, ledger, oracle, factory) are added by W2-B.
"""
