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
