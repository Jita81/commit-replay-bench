"""B1 oracle: pseudonym = HMAC-SHA256(key=secret, msg=b"mandate/pseudonym/v1|" + scope), hex."""

import pytest

from mandate.identity import derive_pseudonym

SECRET = b"0123456789abcdef"


def test_pinned_vector():
    assert (
        derive_pseudonym(SECRET, "immigration-2026")
        == "d16841847c13c3d3a0fbf35536e1345515f15841f7f66206a1fb1a3562578cae"
    )


def test_deterministic():
    assert derive_pseudonym(SECRET, "a") == derive_pseudonym(SECRET, "a")


def test_scopes_are_unlinkable():
    assert derive_pseudonym(SECRET, "consultation-1") != derive_pseudonym(SECRET, "consultation-2")


def test_secrets_differ():
    assert derive_pseudonym(SECRET, "a") != derive_pseudonym(SECRET + b"x", "a")


def test_short_secret_refused():
    with pytest.raises(ValueError):
        derive_pseudonym(b"short", "a")


@pytest.mark.parametrize("scope", ["", "   "])
def test_blank_scope_refused(scope):
    with pytest.raises(ValueError):
        derive_pseudonym(SECRET, scope)
