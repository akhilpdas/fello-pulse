"""T216 (FR-007): passwords are stored only as salted scrypt hashes with their parameters embedded
(so cost can be raised later without breaking old hashes); verification is constant-cost for an
unknown user (so response time does not reveal which emails exist); and a minimum policy holds.

Names the production change that makes it fail: ``pulse.auth.passwords``.
"""

from __future__ import annotations

import hashlib

import pytest

from pulse.auth import passwords
from pulse.auth.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_password,
)

GOOD = "correct horse battery staple"


def test_hash_is_salted_and_never_contains_the_password():
    a, b = hash_password(GOOD), hash_password(GOOD)
    assert a != b  # per-user salt
    assert GOOD not in a
    assert a.startswith("scrypt$")


def test_verify_accepts_the_right_password_and_rejects_the_wrong_one():
    h = hash_password(GOOD)
    assert verify_password(GOOD, h) is True
    assert verify_password(GOOD + "x", h) is False
    assert verify_password("", h) is False


def test_parameters_are_embedded_so_old_hashes_still_verify_after_the_cost_is_raised(monkeypatch):
    h = hash_password(GOOD)
    monkeypatch.setattr(passwords, "SCRYPT_N", passwords.SCRYPT_N * 2)  # cost raised later
    assert verify_password(GOOD, h) is True


def test_unknown_user_still_costs_a_scrypt_computation(monkeypatch):
    calls = []
    real = hashlib.scrypt
    monkeypatch.setattr(passwords.hashlib, "scrypt", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert verify_password("anything at all", None) is False
    assert calls, "no hash computed for an unknown user: timing would reveal which emails exist"


def test_malformed_stored_hash_is_a_failed_login_not_a_crash():
    assert verify_password(GOOD, "not-a-hash") is False
    assert verify_password(GOOD, "scrypt$x$y") is False


@pytest.mark.parametrize("bad", ["short", "elevenchars", "password1234", "123456789012", "qwertyuiop12"])
def test_policy_rejects_short_and_common_passwords(bad):
    with pytest.raises(PasswordPolicyError):
        validate_password(bad, "ana@example.test")


def test_policy_rejects_the_email_itself_and_accepts_a_good_password():
    with pytest.raises(PasswordPolicyError):
        validate_password("ana@example.test", "ana@example.test")
    validate_password(GOOD, "ana@example.test")  # no exception
