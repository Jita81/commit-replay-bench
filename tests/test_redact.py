"""crb.core.redact — every credential shape, and the cap keeps the tail."""

from __future__ import annotations

import pytest

from crb.core.redact import redact, redact_and_cap


@pytest.mark.parametrize(
    ("text", "gone", "marker"),
    [
        ("Authorization: Bearer abcDEF123456789xyz", "abcDEF123456789xyz", "Bearer [REDACTED]"),
        ("authorization=Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNz", "Basic [REDACTED]"),
        ("key sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ here", "ABCDEFGHIJKLMNOP", "[REDACTED-KEY]"),
        ("sk-proj-abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnop", "[REDACTED-KEY]"),
        ("pk-ABCDEFGHIJKLMNOPQRSTUV", "ABCDEFGHIJKLMNOP", "[REDACTED-KEY]"),
        ("token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", "ABCDEFGHIJKLMNOP", "[REDACTED-GH]"),
        ("github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123", "ABCDEFGHIJKLMNOP", "[REDACTED-GH]"),
        ("xoxb-1234567890-abcdefghij", "1234567890-abcdefghij", "[REDACTED-SLACK]"),
        ("AKIAIOSFODNN7EXAMPLE", "IOSFODNN7EXAMPLE", "[REDACTED-AWS]"),
        ("AIzaSyA1234567890abcdefghijklmnopqrstuv", "SyA1234567890", "[REDACTED-GCP]"),
        (
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV",
            "eyJzdWIiOiIxMjM0",
            "[REDACTED-JWT]",
        ),
        ("DATABASE_PASSWORD=hunter22222", "hunter22222", "DATABASE_PASSWORD=[REDACTED]"),
        ("api_key: 'abcdef123456'", "abcdef123456", "api_key=[REDACTED]"),
        ('MY_ACCESS-KEY="zzzzzzzz"', "zzzzzzzz", "MY_ACCESS-KEY=[REDACTED]"),
        ("secret_token=abc123def456&next=1", "abc123def456", "secret_token=[REDACTED]&next=1"),
        (
            "https://user:p4ssw0rd@example.com/repo.git",
            "p4ssw0rd",
            "https://user:[REDACTED]@example.com",
        ),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAAAA\n-----END RSA PRIVATE KEY-----\n",
            "MIIEow",
            "[REDACTED-PRIVATE-KEY]",
        ),
    ],
)
def test_each_pattern(text: str, gone: str, marker: str) -> None:
    out = redact(text)
    assert gone not in out, out
    assert marker in out, out


def test_short_or_benign_values_are_left_alone() -> None:
    benign = "token=abc password: 12345 sk-short AKIA12 'x-y' https://example.com/a:b"
    assert redact(benign) == benign
    assert redact("FAILED tests/test_token.py::test_token_roundtrip - assert x") == (
        "FAILED tests/test_token.py::test_token_roundtrip - assert x"
    )
    assert redact("") == ""


def test_redaction_is_idempotent_and_multi_line() -> None:
    text = "line1 AKIAIOSFODNN7EXAMPLE\nline2 password=supersecret\nline3 ok"
    once = redact(text)
    assert redact(once) == once
    assert once.splitlines()[2] == "line3 ok"
    assert once.count("[REDACTED") == 2


def test_redact_and_cap_keeps_the_tail() -> None:
    text = "\n".join(f"line {i:04d}" for i in range(1000))
    out = redact_and_cap(text, max_chars=100)
    assert len(out) == 100
    assert out.endswith("line 0999")
    assert "line 0000" not in out
    assert redact_and_cap("short") == "short"
    assert len(redact_and_cap("x" * 9000)) == 8000


def test_redact_and_cap_redacts_before_capping() -> None:
    text = "AKIAIOSFODNN7EXAMPLE " + "y" * 50
    out = redact_and_cap(text, max_chars=40)
    assert "AKIAIOSFODNN7EXAMPLE" not in out and out == "y" * 40
