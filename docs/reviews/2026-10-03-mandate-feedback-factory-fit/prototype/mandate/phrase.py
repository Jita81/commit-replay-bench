"""B2 — recovery phrases."""

import hashlib
import random

from mandate.wordlist import WORDS

_SALT = b"mandate/phrase/v1"


def _checksum(first_words: list[str]) -> str:
    return WORDS[hashlib.sha256(" ".join(first_words).encode()).digest()[0]]


def generate_phrase(rng: random.Random | None = None, words: int = 6) -> str:
    if words < 4:
        raise ValueError("a phrase needs at least 4 words")
    rng = rng or random.SystemRandom()
    first = [WORDS[rng.randrange(256)] for _ in range(words - 1)]
    return " ".join([*first, _checksum(first)])


def _normalise(phrase: str) -> list[str]:
    return phrase.strip().lower().split()


def validate_phrase(phrase: str) -> bool:
    try:
        parts = _normalise(phrase)
        if len(parts) < 4 or any(p not in WORDS for p in parts):
            return False
        return parts[-1] == _checksum(parts[:-1])
    except Exception:
        return False


def phrase_to_secret(phrase: str) -> bytes:
    if not validate_phrase(phrase):
        raise ValueError("invalid recovery phrase")
    normalised = " ".join(_normalise(phrase))
    return hashlib.pbkdf2_hmac("sha256", normalised.encode(), _SALT, 100_000)
