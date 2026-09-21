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
              carrying ``RedactingFilter`` and either ``JsonFormatter`` or ``TextFormatter``;
              both redact the rendered traceback (the text one did not before J-TEL-14 —
              an exception message holding a token reached the text log unredacted); a
              record whose ``%``-format is broken is rendered as ``msg + args`` and redacted
              rather than handed raw to ``Handler.handleError``.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/redact.py (the one redaction rule set), src/crb/server/main.py
              and src/crb/server/worker_main.py (call ``configure_logging`` at start-up),
              docs/SECURITY.md (the "secrets never in logs" commitment this enforces),
              docs/DEPLOYMENT.md#9-observability (the log format and shipping)
Tested by:    tests/test_observability_logging.py (the filter, both formatters, the
              start-up call), tests/test_redact.py (the rules)
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
            try:
                rendered = record.getMessage()
            except Exception:
                # a broken %-format: keep the line (msg + args, redacted) instead of letting
                # the formatter raise later and ``Handler.handleError`` print the raw args
                rendered = f"{record.msg} {record.args!r}"
            record.msg = redact(str(rendered))
            record.args = ()
        for k, v in list(record.__dict__.items()):
            if k in _STD_ATTRS:
                continue
            if isinstance(v, str):
                record.__dict__[k] = redact(v)
            elif not isinstance(v, int | float | bool | type(None)):
                # a mapping / list / object extra reaches the formatter as str(v): redact
                # the rendering here, so no non-string extra can carry a secret through
                # (CodeRabbit on PR #3, CWE-532, 2026-09-15)
                record.__dict__[k] = redact(str(v))
        return True


class _RedactedTracebacks(logging.Formatter):
    """Redact the rendered traceback and stack — an exception message can carry the
    credential the request failed with."""

    def formatException(self, ei: Any) -> str:  # noqa: N802 — stdlib name
        return redact(super().formatException(ei))

    def formatStack(self, stack_info: str) -> str:  # noqa: N802 — stdlib name
        return redact(super().formatStack(stack_info))


class TextFormatter(_RedactedTracebacks):
    """The human line format (``fmt=text``) with the traceback redacted."""


class JsonFormatter(_RedactedTracebacks):
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
            obj["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            obj["stack"] = self.formatStack(record.stack_info)
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
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
