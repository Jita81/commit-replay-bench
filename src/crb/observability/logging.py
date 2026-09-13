"""Structured logging with redaction.

``configure_logging(fmt="json")`` installs a JSON formatter (one object per
line: ts, level, logger, msg, plus any ``extra=`` fields) and a filter that
redacts credential shapes from every message and every extra. ``fmt="text"``
keeps a human line format with the same redaction.
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
    def filter(self, record: logging.LogRecord) -> bool:
        with contextlib.suppress(Exception):  # never let logging raise
            record.msg = redact(str(record.getMessage()))
            record.args = ()
        for k, v in list(record.__dict__.items()):
            if k not in _STD_ATTRS and isinstance(v, str):
                record.__dict__[k] = redact(v)
        return True


class JsonFormatter(logging.Formatter):
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
