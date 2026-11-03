"""Password hashing with Argon2 (via pwdlib)."""

from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_password_hash = PasswordHash.recommended()

# Verified against when a login names an unknown user, so a missing account
# costs the same time as a wrong password and cannot be detected by timing.
_DUMMY_HASH = _password_hash.hash("taskflow-dummy-password")


def hash_password(password: str) -> str:
    """Return an Argon2 hash of ``password``."""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check ``password`` against a stored hash; False for unknown/legacy hashes."""
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_HASH)
        return False
    try:
        return _password_hash.verify(password, password_hash)
    except UnknownHashError:
        # Hashes from before Argon2 (e.g. the old SHA-256 scheme) are not
        # recognised; treat them as a failed login instead of a server error.
        return False
