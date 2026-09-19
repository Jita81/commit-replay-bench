"""``configure_logging``: every line — message, ``%``-args, ``extra=`` fields (strings, dicts,
objects), and a traceback — passes the evidence-pack redaction before a handler sees it,
in both the JSON and the text format. SECURITY.md commits that secrets never reach a log;
this is the test behind the enforcement point (J-TEL-14 — the module was self-declared
untested before it).

Navigation
----------
What it is:   The logging suite — ``RedactingFilter``, ``JsonFormatter`` and ``configure_logging``.
What it does: Logs a token in the message, in a ``%`` argument, in a string extra, in a dict
              extra, in an object extra and in an exception's message; asserts every JSON line
              parses, carries ``ts`` / ``level`` / ``logger`` / ``msg`` and the extras, and holds
              no secret; the same for ``fmt=text``; that ``configure_logging`` replaces the
              root handlers (no duplicate lines), sets the level, and never raises on a record
              whose ``%`` formatting is broken.
How:          ``configure_logging(stream=StringIO())`` and a scan of the captured text for the
              secret values; the redaction rules themselves are tests/test_redact.py's.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/observability/logging.py (under test), src/crb/core/redact.py (the rules),
              tests/test_redact.py (the rules' own suite), docs/SECURITY.md (the commitment)
Tested by:    tests/test_observability_logging.py
Touch when:   a new log field type is allow-listed in ``JsonFormatter``, or a new call site
              passes structured extras.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from crb.observability.logging import (
    JsonFormatter,
    RedactingFilter,
    TextFormatter,
    configure_logging,
)

GH = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
SK = "sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZZZZZ"
URL = "https://user:hunter2secret@github.com/acme/repo.git"


@pytest.fixture
def stream() -> io.StringIO:
    return io.StringIO()


@pytest.fixture(autouse=True)
def _restore_root() -> None:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)


def _lines(stream: io.StringIO) -> list[str]:
    return [ln for ln in stream.getvalue().splitlines() if ln.strip()]


def _emit_everything(logger: logging.Logger) -> None:
    logger.info("clone %s with token %s", URL, GH)
    logger.warning("key in extra", extra={"token": SK, "run_id": "r1", "n": 3, "ok": True})
    logger.warning("dict extra", extra={"headers": {"Authorization": f"Bearer {GH}"}})
    logger.warning("object extra", extra={"cfg": type("Cfg", (), {"__str__": lambda s: SK})()})
    try:
        raise RuntimeError(f"auth failed for {GH} at {URL}")
    except RuntimeError:
        logger.exception("build errored")


def test_json_lines_parse_and_carry_no_secret(stream: io.StringIO) -> None:
    configure_logging(fmt="json", level="INFO", stream=stream)
    _emit_everything(logging.getLogger("crb.test.json"))
    lines = _lines(stream)
    assert len(lines) == 5
    text = stream.getvalue()
    for secret in (GH, SK, "hunter2secret"):
        assert secret not in text
    objs = [json.loads(ln) for ln in lines]
    for o in objs:
        assert {"ts", "level", "logger", "msg"} <= set(o)
        assert o["logger"] == "crb.test.json"
    assert (
        objs[0]["msg"]
        == "clone https://user:[REDACTED]@github.com/acme/repo.git with token [REDACTED-GH]"
    )
    assert objs[1]["token"] == "[REDACTED-KEY]" and objs[1]["run_id"] == "r1"
    assert objs[1]["n"] == 3 and objs[1]["ok"] is True  # scalars stay structured
    assert "REDACTED" in objs[2]["headers"] and "Bearer" in objs[2]["headers"]
    assert objs[3]["cfg"] == "[REDACTED-KEY]"
    assert objs[4]["level"] == "ERROR" and "RuntimeError" in objs[4]["exc"]
    assert "[REDACTED-GH]" in objs[4]["exc"] and "[REDACTED]@github.com" in objs[4]["exc"]


def test_text_format_redacts_the_same(stream: io.StringIO) -> None:
    configure_logging(fmt="text", level="DEBUG", stream=stream)
    _emit_everything(logging.getLogger("crb.test.text"))
    text = stream.getvalue()
    assert len(_lines(stream)) >= 5
    for secret in (GH, SK, "hunter2secret"):
        assert secret not in text
    assert "[REDACTED-GH]" in text and "INFO crb.test.text:" in text
    # the traceback is rendered by the stdlib formatter; the filter redacted the message
    # of the exception before it, so the secret in the traceback text is gone too
    assert "RuntimeError: auth failed for [REDACTED-GH]" in text
    assert isinstance(logging.getLogger().handlers[0].formatter, TextFormatter)


def test_configure_logging_replaces_handlers_and_sets_the_level(stream: io.StringIO) -> None:
    other = io.StringIO()
    configure_logging(fmt="json", level="WARNING", stream=other)
    configure_logging(fmt="json", level="WARNING", stream=stream)
    log = logging.getLogger("crb.test.level")
    log.info("dropped by level")
    log.warning("kept")
    assert other.getvalue() == ""  # the earlier handler is gone: no duplicate lines
    assert [json.loads(ln)["msg"] for ln in _lines(stream)] == ["kept"]
    assert logging.getLogger().level == logging.WARNING


def test_filter_never_raises_on_a_broken_record() -> None:
    rec = logging.LogRecord("x", logging.INFO, "f.py", 1, "bad %s %s", (GH,), None)
    assert RedactingFilter().filter(rec) is True  # too few args: getMessage() raises inside
    # … the line is kept as msg + args, redacted, and the args are cleared so no formatter
    # (and no ``Handler.handleError`` fallback) ever sees the raw token
    assert rec.args == () and GH not in str(rec.msg) and "[REDACTED-GH]" in str(rec.msg)
    out = JsonFormatter().format(rec)
    assert json.loads(out)["msg"].startswith("bad %s %s") and GH not in out
