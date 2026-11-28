"""Pruebas unitarias del cifrado en reposo (vexa.security.vault)."""
from vexa.security import vault


def test_text_round_trip_and_prefix():
    cifrado = vault.enc_text("Nota reservada del caso")
    assert cifrado.startswith(vault.TEXT_PREFIX)
    assert "reservada" not in cifrado
    assert vault.dec_text(cifrado) == "Nota reservada del caso"


def test_plain_values_pass_through_unchanged():
    assert vault.dec_text("texto antiguo sin cifrar") == "texto antiguo sin cifrar"
    assert vault.decrypt_bytes(b"sin cifrar") == b"sin cifrar"
    assert not vault.is_encrypted(b"sin cifrar")


def test_each_encryption_is_different_but_decrypts():
    a, b = vault.encrypt_bytes(b"documento"), vault.encrypt_bytes(b"documento")
    assert a != b
    assert vault.is_encrypted(a)
    assert vault.decrypt_bytes(a) == vault.decrypt_bytes(b) == b"documento"


def test_fingerprint_is_short_and_stable():
    huella = vault.key_fingerprint()
    assert len(huella) == 16 and int(huella, 16) >= 0
    assert vault.key_fingerprint(vault.key_bytes()) == huella
