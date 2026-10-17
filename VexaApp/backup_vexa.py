"""Create and restore an encrypted, same-Windows-account VEXA backup.

Close VEXA before running this utility so document files and the watched-folder
queue are not changing while the snapshot is collected.
"""
from __future__ import annotations

import argparse
import io
import os
import sqlite3
import struct
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet, InvalidToken

import vault

MAGIC = b"VEXABAK1"
MAX_WRAPPED_KEY = 16 * 1024
DB_NAME = "vexa_web.db"
KEY_NAME = "vault.key"


class BackupError(ValueError):
    """Backup is invalid, incomplete, or cannot safely be restored."""


def _wrap_key(key: bytes) -> bytes:
    if sys.platform == "win32":
        return b"D" + vault._dpapi(key, True)
    # Non-Windows development installs use the existing VEXA vault key; never
    # put the archive key itself in plaintext in the backup header.
    return b"V" + vault._get().encrypt(key)


def _unwrap_key(wrapped: bytes) -> bytes:
    if not wrapped:
        raise BackupError("El respaldo no contiene una clave válida.")
    if wrapped[:1] == b"D":
        if sys.platform != "win32":
            raise BackupError("Este respaldo requiere Windows y la misma cuenta de Windows.")
        try:
            return vault._dpapi(wrapped[1:], False)
        except Exception as exc:
            raise BackupError("Windows no pudo recuperar la clave con esta cuenta.") from exc
    if wrapped[:1] == b"V" and sys.platform != "win32":
        try:
            return vault._get().decrypt(wrapped[1:])
        except InvalidToken as exc:
            raise BackupError("La clave de VEXA no coincide con la de este respaldo.") from exc
    raise BackupError("El respaldo fue creado en una plataforma incompatible.")


def _add_database_snapshot(source: Path, snapshot: Path) -> None:
    if not source.is_file():
        raise BackupError(f"No se encontró la base de datos: {source}")
    src = sqlite3.connect(source, timeout=30)
    dst = sqlite3.connect(snapshot)
    try:
        src.backup(dst)
        check = dst.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise BackupError("La copia de la base SQLite no pasó integrity_check.")
    finally:
        dst.close()
        src.close()


def create_backup(data_dir, destination, *, watch_dir=None) -> Path:
    """Write an authenticated encrypted archive containing VEXA's local data."""
    root = Path(data_dir).resolve()
    dest = Path(destination).resolve()
    if not root.is_dir():
        raise BackupError(f"No existe la carpeta de datos: {root}")
    try:
        dest.relative_to(root)
    except ValueError:
        pass
    else:
        raise BackupError("Guarda el respaldo fuera de la carpeta de datos de VEXA.")
    if watch_dir is not None:
        watch = Path(watch_dir).resolve()
        try:
            watch.relative_to(root)
        except ValueError as exc:
            raise BackupError(
                "VEXA_WATCH_DIR está fuera de la carpeta de datos; respalda esa carpeta por separado."
            ) from exc

    db_path = root / DB_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vexa-backup-", dir=dest.parent) as work:
        workdir = Path(work)
        snapshot = workdir / DB_NAME
        _add_database_snapshot(db_path, snapshot)
        zip_path = workdir / "payload.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, DB_NAME)
            for item in root.rglob("*"):
                if item.is_symlink():
                    raise BackupError(f"No se respaldan enlaces simbólicos: {item}")
                if (not item.is_file() or item.resolve() == db_path.resolve()
                        or item.name in {DB_NAME + "-wal", DB_NAME + "-shm"}):
                    continue
                archive.write(item, item.relative_to(root).as_posix())
        key = Fernet.generate_key()
        wrapped = _wrap_key(key)
        encrypted = Fernet(key).encrypt(zip_path.read_bytes())
        with dest.open("xb") as output:
            output.write(MAGIC)
            output.write(struct.pack(">I", len(wrapped)))
            output.write(wrapped)
            output.write(encrypted)
    return dest


def _extract_validated(payload: bytes, staging: Path) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            seen = set()
            for info in archive.infolist():
                name = info.filename
                path = PurePosixPath(name)
                mode = (info.external_attr >> 16) & 0o170000
                if (path.is_absolute() or ".." in path.parts or not path.parts
                        or "\\" in name or ":" in name or "\x00" in name or mode == 0o120000):
                    raise BackupError("El respaldo contiene una ruta no permitida.")
                if name in seen:
                    raise BackupError("El respaldo contiene rutas duplicadas.")
                seen.add(name)
            if DB_NAME not in seen or KEY_NAME not in seen:
                raise BackupError("El respaldo no contiene la base de datos y la clave de VEXA.")
            archive.extractall(staging)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BackupError("El contenido del respaldo está dañado.") from exc
    db = staging / DB_NAME
    if not db.is_file():
        raise BackupError("No se pudo restaurar la base de datos.")
    conn = sqlite3.connect(db)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError("La base del respaldo está dañada.")
    finally:
        conn.close()


def restore_backup(backup_path, data_dir, *, replace=False) -> Path:
    """Restore into an empty directory; --replace preserves the previous copy."""
    source = Path(backup_path)
    requested_target = Path(data_dir)
    if requested_target.is_symlink():
        raise BackupError("La carpeta destino no puede ser un enlace simbólico.")
    target = requested_target.resolve()
    try:
        raw = source.read_bytes()
        if not raw.startswith(MAGIC) or len(raw) < len(MAGIC) + 4:
            raise BackupError("El archivo no tiene un formato de respaldo VEXA válido.")
        offset = len(MAGIC)
        wrapped_len = struct.unpack(">I", raw[offset:offset + 4])[0]
        offset += 4
        if wrapped_len == 0 or wrapped_len > MAX_WRAPPED_KEY or offset + wrapped_len >= len(raw):
            raise BackupError("El respaldo tiene una cabecera inválida.")
        key = _unwrap_key(raw[offset:offset + wrapped_len])
        payload = Fernet(key).decrypt(raw[offset + wrapped_len:])
    except InvalidToken as exc:
        raise BackupError("La clave no coincide o el respaldo fue alterado.") from exc
    except OSError as exc:
        raise BackupError(f"No se pudo leer el respaldo: {exc}") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vexa-restore-", dir=target.parent) as temp:
        staging = Path(temp) / "restored"
        staging.mkdir()
        _extract_validated(payload, staging)
        if target.exists() and any(target.iterdir()):
            if not replace:
                raise BackupError("La carpeta destino no está vacía; usa --replace para conservarla como respaldo previo.")
            old = target.with_name(target.name + ".before-restore-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            if old.exists():
                raise BackupError(f"Ya existe la carpeta de recuperación: {old}")
            os.replace(target, old)
            try:
                os.replace(staging, target)
            except Exception:
                os.replace(old, target)
                raise
        else:
            if target.exists():
                target.rmdir()
            os.replace(staging, target)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Respaldo cifrado local de VEXA")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="crear un respaldo")
    create.add_argument("destination", type=Path)
    restore = commands.add_parser("restore", help="restaurar un respaldo")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target", type=Path, default=Path.home() / ".vexa_local")
    restore.add_argument("--replace", action="store_true", help="mover los datos actuales y restaurar")
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            watch = os.environ.get("VEXA_WATCH_DIR") or (Path.home() / ".vexa_local" / "carpeta_vigilada")
            path = create_backup(Path.home() / ".vexa_local", args.destination, watch_dir=watch)
            print(f"Respaldo cifrado creado: {path}")
        else:
            path = restore_backup(args.backup, args.target, replace=args.replace)
            print(f"Datos restaurados en: {path}")
        return 0
    except BackupError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
