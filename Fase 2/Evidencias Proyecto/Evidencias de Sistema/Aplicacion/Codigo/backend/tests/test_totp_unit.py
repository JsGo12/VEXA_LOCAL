"""Pruebas unitarias del doble factor (TOTP, RFC 6238)."""
from vexa.security import totp

# Vector de prueba del RFC 6238 (SHA-1): clave ASCII "12345678901234567890" en base32.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_code_matches_rfc_6238_vectors():
    assert totp.code_at(RFC_SECRET, 59 // 30) == "287082"
    assert totp.code_at(RFC_SECRET, 1111111109 // 30) == "081804"


def test_new_secret_is_base32_without_padding():
    secret = totp.new_secret()
    assert len(secret) == 32
    assert "=" not in secret
    assert totp.code_at(secret, 1).isdigit()


def test_verify_returns_step_and_rejects_reuse():
    assert totp.verify(RFC_SECRET, "287082", last_step=0, now=59) == 1
    assert totp.verify(RFC_SECRET, "287082", last_step=1, now=59) is None


def test_verify_ignores_spaces_and_rejects_wrong_length():
    assert totp.verify(RFC_SECRET, "287 082", now=59) == 1
    assert totp.verify(RFC_SECRET, "28708", now=59) is None
    assert totp.verify(RFC_SECRET, "", now=59) is None
