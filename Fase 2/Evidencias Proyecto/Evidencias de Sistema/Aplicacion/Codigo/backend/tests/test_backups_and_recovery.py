"""Respaldo automático, formato VEXABAK2 y clave de recuperación (restaurar en otro equipo)."""
import sqlite3
import time
from types import SimpleNamespace

import pytest

from helpers import CSRF, _client_as, _web_app, add_user, admin_id
from vexa.security import recovery, vault
from vexa.services import backups


def _data_dir(tmp_path, name="data"):
    data = tmp_path / name
    (data / "case_documents").mkdir(parents=True)
    vault.configure(data)
    con = sqlite3.connect(data / "vexa_web.db")
    con.execute("CREATE TABLE prueba(x TEXT)")
    con.execute("INSERT INTO prueba VALUES ('dato')")
    con.commit()
    con.close()
    vault.write_encrypted(data / "case_documents" / "doc.txt", b"Documento confidencial")
    return data


def _settings(tmp_path, data, **extra):
    return SimpleNamespace(data_dir=data, watch_dir=data / "carpeta_vigilada", backups_dir=data / "backups",
                           backup_dir=tmp_path / "respaldos", backup_hours=24, backup_keep=3, **extra)


def test_new_backups_carry_dpapi_and_vault_wrappings(tmp_path):
    data = _data_dir(tmp_path)
    path = backups.create_backup(data, tmp_path / "a.vexabackup")
    entries, _ = backups._parse(path.read_bytes())
    kinds = [e[:1] for e in entries]
    assert path.read_bytes().startswith(backups.MAGIC) and b"R" in kinds
    restored = backups.restore_backup(path, tmp_path / "restaurado")
    assert (restored / "vexa_web.db").is_file()


def test_recovery_key_round_trip_and_wrong_password(tmp_path):
    data = _data_dir(tmp_path)
    info = recovery.export_recovery(tmp_path / "usb" / "clave.vexakey", "una-frase-larga-segura", data_dir=data)
    assert recovery.load_recovery(tmp_path / "usb" / "clave.vexakey", "una-frase-larga-segura") == vault.key_bytes()
    with pytest.raises(recovery.RecoveryError, match="contraseña"):
        recovery.load_recovery(tmp_path / "usb" / "clave.vexakey", "otra-frase-cualquiera")
    with pytest.raises(recovery.RecoveryError, match="al menos"):
        recovery.export_recovery(tmp_path / "corta.vexakey", "corta")
    with pytest.raises(recovery.RecoveryError, match="Ya existe"):
        recovery.export_recovery(tmp_path / "usb" / "clave.vexakey", "una-frase-larga-segura")
    status = recovery.status(data)
    assert status["exported"] and status["matches"] and "fingerprint" not in status
    assert info["fingerprint"] not in (tmp_path / "usb" / "clave.vexakey").read_bytes().decode("latin-1")


def test_restore_on_another_machine_with_recovery_key(tmp_path, monkeypatch):
    data = _data_dir(tmp_path)
    original_key = vault.key_bytes()
    recovery.export_recovery(tmp_path / "clave.vexakey", "una-frase-larga-segura")
    backup = backups.create_backup(data, tmp_path / "r.vexabackup")

    # "Otro equipo": otra cuenta (DPAPI no abre la envoltura D) y otro vault.
    real_dpapi = vault._dpapi
    monkeypatch.setattr(vault, "_dpapi", lambda d, protect: real_dpapi(d, True) if protect else (_ for _ in ()).throw(OSError("otra cuenta")))
    vault.configure(tmp_path / "otro_equipo")
    with pytest.raises(backups.BackupError, match="clave de recuperación"):
        backups.restore_backup(backup, tmp_path / "nuevo")
    key = recovery.load_recovery(tmp_path / "clave.vexakey", "una-frase-larga-segura")
    restored = backups.restore_backup(backup, tmp_path / "nuevo", recovery_key=key)

    # El vault restaurado abre los documentos cifrados del respaldo.
    monkeypatch.setattr(vault, "_dpapi", real_dpapi)
    vault.configure(restored)
    assert vault.key_bytes() == original_key
    assert vault.read_bytes(restored / "case_documents" / "doc.txt") == b"Documento confidencial"


def test_automatic_backup_keeps_only_the_latest(tmp_path):
    data = _data_dir(tmp_path)
    settings = _settings(tmp_path, data)
    assert backups.backup_due(settings)
    for _ in range(5):
        backups.run_backup(settings)
        time.sleep(1.05)                                  # nombres con segundos distintos
    files = backups.list_backups(settings.backup_dir)
    assert len(files) == 3 and not backups.backup_due(settings)
    status = backups.read_status(data)
    assert status["last_ok"] and status["last_error"] is None
    assert backups.backup_due(settings, now=time.time() + 25 * 3600)
    assert not backups.backup_due(SimpleNamespace(**{**vars(settings), "backup_hours": 0}))


def test_backup_dir_inside_data_dir_is_rejected():
    from vexa.config import ConfigError, load_settings
    with pytest.raises(ConfigError, match="fuera de la carpeta de datos"):
        load_settings({"VEXA_DATA_DIR": "C:/vexa_datos", "VEXA_BACKUP_DIR": "C:/vexa_datos/respaldos"},
                      use_env_file=False)


def test_backups_tab_is_admin_only_and_manual_backup_works(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    settings = web.app.extensions["vexa"].settings
    object.__setattr__(settings, "backup_dir", tmp_path / "respaldos")    # Settings es inmutable
    admin = _client_as(web, admin_id(web))
    page = admin.get("/admin?tab=respaldos").get_data(as_text=True)
    assert 'id="tab-respaldos"' in page and "Falta crearla" in page and "Aún no hay respaldos" in page
    response = admin.post("/admin/respaldos", data={"csrf_token": CSRF})
    assert response.headers["Location"].endswith("/admin?tab=respaldos")
    assert len(backups.list_backups(tmp_path / "respaldos")) == 1
    chief = _client_as(web, add_user(web, "jefa", "chief_lawyer"))
    assert 'id="tab-respaldos"' not in chief.get("/admin").get_data(as_text=True)
    chief.post("/admin/respaldos", data={"csrf_token": CSRF})
    assert len(backups.list_backups(tmp_path / "respaldos")) == 1
