"""Redaction for anything that leaves the sandbox: test output, diffs, transcripts.

Conservative regexes for the credential shapes that show up in CI logs. This is
defence in depth — the executors already strip the operator's environment — and
it runs on every string an evidence pack stores.
"""

from __future__ import annotations

import re

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
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def redact_and_cap(text: str, *, max_chars: int = 8000) -> str:
    out = redact(text)
    if len(out) > max_chars:
        return out[-max_chars:]
    return out
