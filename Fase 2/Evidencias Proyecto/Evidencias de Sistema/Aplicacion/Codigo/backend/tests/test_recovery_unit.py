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
