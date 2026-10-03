"""B2 oracle: recovery phrases.

generate_phrase: (words-1) words drawn with rng.randrange(256) from WORDS, then a checksum word
WORDS[sha256(" ".join(first_words)).digest()[0]]; single-space joined; words < 4 -> ValueError;
rng defaults to random.SystemRandom().
validate_phrase: normalise (strip, lower-case, split on any whitespace); True iff >= 4 words,
all in WORDS and the checksum matches. Never raises.
phrase_to_secret: ValueError if invalid; else pbkdf2_hmac("sha256", normalised.encode(),
b"mandate/phrase/v1", 100_000) -> 32 bytes.
"""

import random

import pytest

from mandate.phrase import generate_phrase, phrase_to_secret, validate_phrase

VALID = "babe babi babo babu bada biki"


def test_generate_seeded():
    assert generate_phrase(random.Random(42)) == "baso bafo beti bepi beme bima"


def test_generate_length():
    assert len(generate_phrase(random.Random(1), words=8).split()) == 8


def test_generate_too_short():
    with pytest.raises(ValueError):
        generate_phrase(random.Random(1), words=3)


def test_generated_phrases_validate():
    rng = random.Random(7)
    assert all(validate_phrase(generate_phrase(rng)) for _ in range(50))


def test_validate_normalises():
    assert validate_phrase("  BABE babi\tbabo  babu bada BIKI ")


@pytest.mark.parametrize(
    "bad",
    ["", "babe babi biki", "babe babi babo babu bada babe", "babe babi babo babu bada zzzz", None],
)
def test_validate_rejects(bad):
    assert validate_phrase(bad) is False


def test_secret_pinned():
    assert (
        phrase_to_secret(VALID).hex()
        == "b4c23decb2a4aa241a1f5e62609ebc385403db63d68a3a929198019ae5ed2408"
    )


def test_secret_same_for_normalised_forms():
    assert phrase_to_secret(VALID.upper()) == phrase_to_secret(VALID)


def test_secret_refuses_invalid():
    with pytest.raises(ValueError):
        phrase_to_secret("babe babi babo babu bada babe")
