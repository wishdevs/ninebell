"""bcrypt hash_password/verify_password 단위 검증(DB 불필요)."""

from __future__ import annotations

from app.core.security import hash_password, verify_password


def test_hash_and_verify_roundtrip():
    h = hash_password("1111")
    assert h != "1111"  # 평문이 아님
    assert verify_password("1111", h) is True
    assert verify_password("9999", h) is False


def test_verify_returns_false_on_corrupt_hash():
    assert verify_password("1111", "not-a-bcrypt-hash") is False
