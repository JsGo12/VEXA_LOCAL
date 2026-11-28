"""Pruebas unitarias de la clave de recuperación."""
import pytest

from vexa.security import recovery, vault

FRASE = "frase de recuperacion larga"


def test_short_passphrase_is_rejected(tmp_path):
    with pytest.raises(recovery.RecoveryError):
        recovery.export_recovery(tmp_path / "clave.vexakey", "corta")
    assert not (tmp_path / "clave.vexakey").exists()


def test_export_and_load_round_trip(tmp_path):
    info = recovery.export_recovery(tmp_path / "clave.vexakey", FRASE)
    assert info["fingerprint"] == vault.key_fingerprint()
    assert recovery.load_recovery(tmp_path / "clave.vexakey", FRASE) == vault.key_bytes()


def test_existing_file_is_never_overwritten(tmp_path):
    destino = tmp_path / "clave.vexakey"
    destino.write_bytes(b"otro archivo")
    with pytest.raises(recovery.RecoveryError):
        recovery.export_recovery(destino, FRASE)
    assert destino.read_bytes() == b"otro archivo"
