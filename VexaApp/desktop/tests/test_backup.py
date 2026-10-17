import io
import sqlite3
import zipfile

import pytest

import backup_vexa
import vault


def _sample_data(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    vault.configure(data)
    with sqlite3.connect(data / "vexa_web.db") as db:
        db.execute("CREATE TABLE cases (title TEXT NOT NULL)")
        db.execute("INSERT INTO cases VALUES ('Caso confidencial')")
    document = data / "case_documents" / "document.enc"
    document.parent.mkdir()
    vault.write_encrypted(document, b"Contenido reservado")
    return data, document


def test_encrypted_backup_restores_database_and_documents(tmp_path):
    data, _ = _sample_data(tmp_path)
    backup = tmp_path / "external" / "vexa.vexabackup"

    backup_vexa.create_backup(data, backup)

    raw_backup = backup.read_bytes()
    assert raw_backup.startswith(backup_vexa.MAGIC)
    assert b"Caso confidencial" not in raw_backup
    restored = tmp_path / "restored"
    backup_vexa.restore_backup(backup, restored)
    with sqlite3.connect(restored / "vexa_web.db") as db:
        assert db.execute("SELECT title FROM cases").fetchone()[0] == "Caso confidencial"
    vault.configure(restored)
    assert vault.read_bytes(restored / "case_documents" / "document.enc") == b"Contenido reservado"


def test_backup_refuses_external_watched_directory(tmp_path):
    data, _ = _sample_data(tmp_path)
    external_watch = tmp_path / "watched"
    external_watch.mkdir()

    with pytest.raises(backup_vexa.BackupError, match="VEXA_WATCH_DIR"):
        backup_vexa.create_backup(data, tmp_path / "backup.vexabackup", watch_dir=external_watch)


def test_restore_refuses_nonempty_destination_without_replace(tmp_path):
    data, _ = _sample_data(tmp_path)
    backup = backup_vexa.create_backup(data, tmp_path / "backup.vexabackup")
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(backup_vexa.BackupError, match="no está vacía"):
        backup_vexa.restore_backup(backup, target)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_rejects_tampered_archive(tmp_path):
    data, _ = _sample_data(tmp_path)
    backup = backup_vexa.create_backup(data, tmp_path / "backup.vexabackup")
    damaged = bytearray(backup.read_bytes())
    # Change an authenticated ciphertext byte (the final base64 character may
    # contain unused bits, so toggling it is not guaranteed to alter the token).
    damaged[-20] ^= 1
    backup.write_bytes(damaged)

    with pytest.raises(backup_vexa.BackupError, match="alterado"):
        backup_vexa.restore_backup(backup, tmp_path / "restored")


def test_restore_replace_preserves_previous_directory(tmp_path):
    data, _ = _sample_data(tmp_path)
    backup = backup_vexa.create_backup(data, tmp_path / "backup.vexabackup")
    target = tmp_path / "existing"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")

    backup_vexa.restore_backup(backup, target, replace=True)

    preserved = list(tmp_path.glob("existing.before-restore-*"))
    assert len(preserved) == 1
    assert (preserved[0] / "old.txt").read_text(encoding="utf-8") == "old"
    assert (target / "vexa_web.db").is_file()


def test_extract_rejects_path_traversal(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../outside.txt", "no")

    with pytest.raises(backup_vexa.BackupError, match="ruta no permitida"):
        backup_vexa._extract_validated(payload.getvalue(), tmp_path)
    assert not (tmp_path.parent / "outside.txt").exists()
