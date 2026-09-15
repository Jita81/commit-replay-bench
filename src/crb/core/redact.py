"""Redaction for anything that leaves the sandbox: test output, diffs, transcripts.

Conservative regexes for the credential shapes that show up in CI logs. This is
defence in depth — the executors already strip the operator's environment — and
it runs on every string an evidence pack stores.

Navigation
----------
What it is:   The redactor — ``redact`` and its two capping variants, applied to every
              string that leaves an execution sandbox before it is stored.
What it does: Replaces bearer / basic authorisation values, well-known API-key prefixes,
              JWTs, ``key=value`` secrets, URL userinfo and private-key blocks with
              ``[REDACTED…]`` markers; ``redact_and_cap`` keeps the tail (test output's
              verdict is last), ``redact_and_cap_head`` the head (an error's kind is its
              prefix). Never raises; never claims completeness.
How:          An ordered tuple of compiled patterns applied in sequence; the caps cut
              after redaction so a secret straddling the cut cannot survive.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/grade.py (test-run tails), src/crb/core/lint.py (lint tails),
              src/crb/core/services.py (service logs), src/crb/core/signoff.py and
              src/crb/core/review.py (human free text), src/crb/observability/logging.py
              (log lines), src/crb/builders/base.py (builder error strings, head-capped)
Tested by:    tests/test_redact.py, tests/test_execution.py, tests/test_services.py
Touch when:   a client's CI output carries a credential shape not in the table (add the
              pattern with a fixture in tests/test_redact.py and a line in
              docs/DATA-RETENTION.md#3-redaction); never loosen a pattern to make output
              more readable.
"""

from __future__ import annotations

import re

#: ``(pattern, replacement)`` in the order applied. Specific shapes (known prefixes,
#: JWTs) come before the generic ``key=value`` rule so a token keeps its family marker.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # bearer / basic auth headers
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
        r"\1\2 [REDACTED]",
    ),
    # well-known token prefixes
    (re.compile(r"\b(sk|rk|pk)-(?:live|test|proj|ant)?-?[A-Za-z0-9_-]{16,}\b"), "[REDACTED-KEY]"),
    (re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,}\b"), "[REDACTED-GH]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED-SLACK]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED-AWS]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "[REDACTED-GCP]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "[REDACTED-JWT]",
    ),
    # key=value secrets in env dumps / URLs
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:secret|token|password|passwd|api[_-]?key|access[_-]?key)[A-Z0-9_]*)\s*[=:]\s*['\"]?([^\s'\"&]{6,})"
        ),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(?i)(https?://[^/\s:@]+:)[^@\s/]+(@)"), r"\1[REDACTED]\2"),
    # private key blocks
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED-PRIVATE-KEY]",
    ),
)


def redact(text: str) -> str:
    """``text`` with every matched credential shape replaced by its marker."""
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def redact_and_cap(text: str, *, max_chars: int = 8000) -> str:
    """Redact, then keep the *tail* — right for test output, where the verdict is last."""
    out = redact(text)
    if len(out) > max_chars:
        return out[-max_chars:]
    return out


def redact_and_cap_head(text: str, *, max_chars: int = 2000) -> str:
    """Redact, then keep the *head* — for error strings whose kind is read off their
    prefix (``network:``, ``protocol violation:``, ``model_error:``). A docker refusal
    longer than the cap, capped tail-first, lost its ``network:`` head: the outcome no
    longer counted as violated and the ledger read the row as ``harness``
    (mesh-client, 2026-09-15)."""
    out = redact(text)
    if len(out) > max_chars:
        return out[: max(1, max_chars - 2)].rstrip() + " …"
    return out
