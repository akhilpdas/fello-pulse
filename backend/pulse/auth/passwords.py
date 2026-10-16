"""Password hashing and policy (FR-007). Pure: no database, no settings.

scrypt from the standard library -- no dependency for a primitive this size. The stored form is
``scrypt$<N>$<r>$<p>$<salt_b64>$<hash_b64>`` so the cost can be raised later and old hashes still verify.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 2**14  # ~16 MiB, tens of ms; raise over time -- stored hashes carry their own parameters
SCRYPT_R = 8
SCRYPT_P = 1
_KEY_LEN = 32
_MAXMEM = 128 * 1024 * 1024
MIN_LENGTH = 12

# A deliberately small deny-list: the guesses an attacker tries first. Length does the real work.
_COMMON = {
    "password1234", "123456789012", "qwertyuiop12", "password12345", "letmein12345", "welcome12345",
    "iloveyou1234", "administrator", "changeme1234", "000000000000", "111111111111", "abcdefghijkl",
}


class PasswordPolicyError(ValueError):
    pass


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=_KEY_LEN, maxmem=_MAXMEM)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """False for a wrong password, an unknown user (``stored`` is None) or a malformed hash. An unknown
    user still costs one scrypt computation so response time does not reveal which emails exist."""
    if stored is None:
        _scrypt(password, b"\x00" * 16, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        return False
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = _scrypt(password, base64.b64decode(salt_b64), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def validate_password(password: str, email: str) -> None:
    """Raise ``PasswordPolicyError`` if the password is unacceptable for this email."""
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_LENGTH} characters")
    if password.lower() == email.lower():
        raise PasswordPolicyError("password must not be the email address")
    if password.lower() in _COMMON:
        raise PasswordPolicyError("password is too common")
