"""``crb serve`` — run the API under uvicorn.

The CLI (W1-D) imports :func:`serve`; this module deliberately does not import
``crb.cli``. ``uvicorn --factory crb.server.main:create_app`` also works for
process managers that prefer to own the server loop.

Access logging is ours (JSON, redacted, with request ids) so uvicorn's own access
log is off. Proxy headers are honoured only from ``CRB_TRUSTED_PROXIES``.

Navigation
----------
What it is:   ``crb serve`` — the uvicorn runner for the API, and the ``--factory`` entry.
What it does: Builds ``Settings`` from the environment, configures JSON logging, creates the
              app and blocks in uvicorn with uvicorn's own access log off (ours is the
              redacted one) and proxy headers honoured only from ``CRB_TRUSTED_PROXIES``.
How:          ``serve`` → ``Settings()`` → ``configure_logging`` → ``create_app`` →
              ``uvicorn.run``; ``build_app`` is the same minus the run, for process managers.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/app.py (``create_app``), src/crb/server/settings.py (bind host /
              port, log format, trusted proxies), src/crb/cli/commands/service.py (the ``crb
              serve`` command that calls ``serve``), deploy/entrypoint.sh (the container's
              ``serve`` role), src/crb/observability/logging.py (``configure_logging``)
Tested by:    untested — a blocking uvicorn loop; ``create_app`` and the settings it passes are
              covered by tests/test_server_app.py and the container role by
              tests/test_deploy_health_probes.py
Touch when:   never for a new repository; only when a uvicorn option changes (document it in
              docs/DEPLOYMENT.md).
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from crb.observability.logging import configure_logging
from crb.server.app import create_app
from crb.server.settings import Settings

log = logging.getLogger("crb.server")


def build_app() -> FastAPI:
    """Factory for ``uvicorn --factory``: settings from the environment."""
    settings = Settings()
    configure_logging(fmt=settings.log_format, level=settings.log_level)
    return create_app(settings)


def serve(
    host: str | None = None, port: int | None = None, *, settings: Settings | None = None
) -> None:
    """Block serving the app. ``host``/``port`` default to ``CRB_BIND_HOST``/``CRB_BIND_PORT``."""
    settings = settings or Settings()
    configure_logging(fmt=settings.log_format, level=settings.log_level)
    app = create_app(settings)
    bind_host = host or settings.bind_host
    bind_port = port or settings.bind_port
    log.info("serving on http://%s:%d (env=%s)", bind_host, bind_port, settings.env)
    uvicorn.run(
        app,
        host=bind_host,
        port=bind_port,
        log_config=None,
        access_log=False,
        proxy_headers=bool(settings.trusted_proxies),
        forwarded_allow_ips=",".join(settings.trusted_proxies) or None,
        server_header=False,
        date_header=True,
    )


__all__ = ["build_app", "create_app", "serve"]
