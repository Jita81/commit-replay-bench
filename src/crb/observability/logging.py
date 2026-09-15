"""Structured logging with redaction.

``configure_logging(fmt="json")`` installs a JSON formatter (one object per
line: ts, level, logger, msg, plus any ``extra=`` fields) and a filter that
redacts credential shapes from every message and every extra. ``fmt="text"``
keeps a human line format with the same redaction.

Navigation
----------
What it is:   Process-wide logging setup for the API, the worker and the CLI: a redacting
              filter, a JSON formatter and ``configure_logging``.
What it does: Guarantees no log line — message, ``extra=`` field or traceback — can carry a
              credential, by running the same ``redact`` as evidence packs on every record
              before any handler sees it; emits one JSON object per line for log shippers.
How:          ``configure_logging`` replaces the root handlers with one ``StreamHandler``
              carrying ``RedactingFilter`` and either ``JsonFormatter`` or a text formatter.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/redact.py (the one redaction rule set), src/crb/server/main.py
              and src/crb/server/worker_main.py (call ``configure_logging`` at start-up),
              docs/SECURITY.md (the "secrets never in logs" commitment this enforces)
Tested by:    untested — no test imports this module; the redaction rules it applies are
              covered by tests/test_redact.py, and the start-up call sites by the server
              suites, but the filter and formatter themselves have no direct test
Touch when:   never for a new repository; a new credential shape is a rule in
              src/crb/core/redact.py (with its test), not a change here; a new log field
              type that ``JsonFormatter`` should keep structured is added to its allowlist.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import sys
from typing import Any

from crb.core.redact import redact

_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class RedactingFilter(logging.Filter):
    """Redact the rendered message and every string ``extra`` in place; always passes."""

    def filter(self, record: logging.LogRecord) -> bool:
        # The message is rendered here so a secret inside an %-arg is redacted too.
        with contextlib.suppress(Exception):  # never let logging raise
            record.msg = redact(str(record.getMessage()))
            record.args = ()
        for k, v in list(record.__dict__.items()):
            if k not in _STD_ATTRS and isinstance(v, str):
                record.__dict__[k] = redact(v)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ``ts``, ``level``, ``logger``, ``msg``, the extras
    (scalars kept, anything else stringified) and a redacted ``exc`` when present."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts": _dt.datetime.fromtimestamp(record.created, _dt.UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD_ATTRS and not k.startswith("_"):
                obj[k] = v if isinstance(v, str | int | float | bool | type(None)) else str(v)
        if record.exc_info:
            obj["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(obj, ensure_ascii=False, default=str)


def configure_logging(fmt: str = "json", level: str = "INFO", stream: Any = None) -> None:
    """Install the redacting handler on the root logger (replacing any existing ones)."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.addFilter(RedactingFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
