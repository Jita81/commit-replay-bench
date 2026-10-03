"""B1 — pseudonym derivation."""

import hashlib
import hmac

_PREFIX = b"mandate/pseudonym/v1|"
_MIN_SECRET_LEN = 16


def derive_pseudonym(secret: bytes, scope: str) -> str:
    if len(secret) < _MIN_SECRET_LEN:
        raise ValueError("secret too short")
    if not scope.strip():
        raise ValueError("scope must not be blank")
    msg = _PREFIX + scope.encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()
