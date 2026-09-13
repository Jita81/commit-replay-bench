"""``crb serve`` — run the API under uvicorn.

The CLI (W1-D) imports :func:`serve`; this module deliberately does not import
``crb.cli``. ``uvicorn --factory crb.server.main:create_app`` also works for
process managers that prefer to own the server loop.

Access logging is ours (JSON, redacted, with request ids) so uvicorn's own access
log is off. Proxy headers are honoured only from ``CRB_TRUSTED_PROXIES``.
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
