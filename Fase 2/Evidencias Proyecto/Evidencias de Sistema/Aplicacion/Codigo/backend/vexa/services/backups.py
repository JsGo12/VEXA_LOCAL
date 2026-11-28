"""Respaldos cifrados de VEXA: creación, restauración y respaldo automático del servidor.

Formato VEXABAK2 (actual): la clave aleatoria del archivo se guarda envuelta de dos formas:
    D  con DPAPI (misma cuenta de Windows: restauración normal en el mismo servidor)
    R  con la clave del vault (permite restaurar en OTRO equipo usando la clave de recuperación)
Formato VEXABAK1 (anterior): una sola envoltura (D en Windows, V en otros sistemas). Se sigue leyendo.

El respaldo automático corre dentro del servidor, sin detenerlo: la base se copia con la API de respaldo
de SQLite (consistente aunque haya escrituras) y los documentos ya están cifrados en disco.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet, InvalidToken

from vexa.security import vault

LOGGER = logging.getLogger(__name__)
MAGIC_V1 = b"VEXABAK1"
MAGIC = b"VEXABAK2"
MAX_WRAPPED_KEY = 16 * 1024
DB_NAME = "vexa_web.db"
KEY_NAME = "vault.key"
STATUS_FILE = "respaldos.json"
FILE_PREFIX = "vexa-"
FILE_SUFFIX = ".vexabackup"
CLOUD_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud")
_run_lock = threading.Lock()


class BackupError(ValueError):
    """El respaldo no es válido, está incompleto o no se puede restaurar con seguridad."""


# ------------------------------------------------------------------ envolturas de la clave
def _wrap_dpapi(key: bytes) -> bytes:
    return b"D" + vault._dpapi(key, True)


def _wrap_vault(key: bytes) -> bytes:
    return b"R" + vault._get().encrypt(key)


def _unwrap(entries: list[bytes], recovery_key: bytes | None):
    """Prueba cada envoltura. Devuelve (clave del archivo, se_usó_la_clave_de_recuperación)."""
    errors = []
    for wrapped in entries:
        kind, body = wrapped[:1], wrapped[1:]
        try:
            if kind == b"D" and sys.platform == "win32":
                return vault._dpapi(body, False), False
            if kind == b"R" and recovery_key is not None:
                return Fernet(recovery_key).decrypt(body), True
            if kind == b"R" and recovery_key is None:
                try:
                    return vault._get().decrypt(body), False      # mismo vault (mismo equipo)
                except InvalidToken:
                    errors.append("R")
            if kind == b"V" and sys.platform != "win32":
                return vault._get().decrypt(body), False
        except Exception:
            errors.append(kind.decode(errors="replace"))
    if recovery_key is None and any(w[:1] == b"R" for w in entries):
        raise BackupError("Esta cuenta de Windows no puede abrir el respaldo. Usa la clave de recuperación "
                          "(--clave-recuperacion).")
    raise BackupError("La clave no coincide o el respaldo fue creado en una plataforma incompatible.")


def _parse(raw: bytes):
    """Devuelve (envolturas, datos cifrados) para VEXABAK1 y VEXABAK2."""
    if raw.startswith(MAGIC_V1) and len(raw) > len(MAGIC_V1) + 4:
        offset = len(MAGIC_V1)
        size = struct.unpack(">I", raw[offset:offset + 4])[0]
        offset += 4
        if size == 0 or size > MAX_WRAPPED_KEY or offset + size >= len(raw):
            raise BackupError("El respaldo tiene una cabecera inválida.")
        return [raw[offset:offset + size]], raw[offset + size:]
    if raw.startswith(MAGIC) and len(raw) > len(MAGIC) + 4:
        offset = len(MAGIC)
        count = struct.unpack(">I", raw[offset:offset + 4])[0]
        offset += 4
        if not 1 <= count <= 8:
            raise BackupError("El respaldo tiene una cabecera inválida.")
        entries = []
        for _ in range(count):
            size = struct.unpack(">I", raw[offset:offset + 4])[0]
            offset += 4
            if size == 0 or size > MAX_WRAPPED_KEY or offset + size >= len(raw):
                raise BackupError("El respaldo tiene una cabecera inválida.")
            entries.append(raw[offset:offset + size])
            offset += size
        return entries, raw[offset:]
    raise BackupError("El archivo no tiene un formato de respaldo VEXA válido.")


# ----------------------------------------------------------------------------- crear
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


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def create_backup(data_dir, destination, *, watch_dir=None, exclude_dirs=()) -> Path:
    """Escribe un archivo cifrado y autenticado con los datos locales de VEXA."""
    root = Path(data_dir).resolve()
    dest = Path(destination).resolve()
    if not root.is_dir():
        raise BackupError(f"No existe la carpeta de datos: {root}")
    if _inside(dest, root):
        raise BackupError("Guarda el respaldo fuera de la carpeta de datos de VEXA.")
    if watch_dir is not None and not _inside(Path(watch_dir).resolve(), root):
        raise BackupError("VEXA_WATCH_DIR está fuera de la carpeta de datos; respalda esa carpeta por separado.")
    skip = [Path(d).resolve() for d in exclude_dirs]
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
                        or item.name in {DB_NAME + "-wal", DB_NAME + "-shm", "vexa_server.lock", "server.json"}
                        or any(_inside(item.resolve(), s) for s in skip)):
                    continue
                archive.write(item, item.relative_to(root).as_posix())
        key = Fernet.generate_key()
        entries = [_wrap_vault(key)]
        if sys.platform == "win32":
            entries.insert(0, _wrap_dpapi(key))
        encrypted = Fernet(key).encrypt(zip_path.read_bytes())
        with dest.open("xb") as output:
            output.write(MAGIC)
            output.write(struct.pack(">I", len(entries)))
            for wrapped in entries:
                output.write(struct.pack(">I", len(wrapped)))
                output.write(wrapped)
            output.write(encrypted)
    return dest


# ------------------------------------------------------------------------- restaurar
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


def restore_backup(backup_path, data_dir, *, replace=False, recovery_key: bytes | None = None) -> Path:
    """Restaura en una carpeta vacía; con replace=True conserva la carpeta anterior al lado.

    Con `recovery_key` (de la clave de recuperación) se puede restaurar en otro equipo o cuenta: la clave
    del vault restaurada se vuelve a proteger para la cuenta actual."""
    source = Path(backup_path)
    requested_target = Path(data_dir)
    if requested_target.is_symlink():
        raise BackupError("La carpeta destino no puede ser un enlace simbólico.")
    target = requested_target.resolve()
    try:
        entries, encrypted = _parse(source.read_bytes())
        key, used_recovery = _unwrap(entries, recovery_key)
        payload = Fernet(key).decrypt(encrypted)
    except InvalidToken as exc:
        raise BackupError("La clave no coincide o el respaldo fue alterado.") from exc
    except OSError as exc:
        raise BackupError(f"No se pudo leer el respaldo: {exc}") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vexa-restore-", dir=target.parent) as temp:
        staging = Path(temp) / "restored"
        staging.mkdir()
        _extract_validated(payload, staging)
        if used_recovery:
            # El vault.key del archivo está protegido para la cuenta anterior: se reemplaza por la misma
            # clave (la de recuperación) protegida para esta cuenta. Los datos cifrados no cambian.
            (staging / KEY_NAME).write_bytes(vault.protected_key_file(recovery_key))
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


# ----------------------------------------------------------------- respaldo automático
def looks_like_cloud(path: Path) -> bool:
    return any(marker in str(path).lower() for marker in CLOUD_MARKERS)


def list_backups(backup_dir: Path) -> list[dict]:
    """Respaldos de la carpeta, del más reciente al más antiguo."""
    try:
        files = [p for p in Path(backup_dir).glob(f"{FILE_PREFIX}*{FILE_SUFFIX}") if p.is_file()]
    except OSError:
        return []
    result = []
    for p in sorted(files, key=lambda f: f.stat().st_mtime, reverse=True):
        stat = p.stat()
        result.append({"name": p.name, "path": str(p), "size": stat.st_size,
                       "when": datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m-%Y %H:%M")})
    return result


def read_status(data_dir) -> dict:
    try:
        return json.loads((Path(data_dir) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(data_dir, **values) -> None:
    status = {**read_status(data_dir), **values}
    try:
        (Path(data_dir) / STATUS_FILE).write_text(json.dumps(status), encoding="utf-8")
    except OSError:
        LOGGER.warning("No se pudo guardar el estado de los respaldos.")


def run_backup(settings, reason: str = "automático") -> Path:
    """Crea un respaldo en VEXA_BACKUP_DIR y conserva solo los últimos VEXA_BACKUP_KEEP."""
    if not _run_lock.acquire(blocking=False):
        raise BackupError("Ya hay un respaldo en curso; espera a que termine.")
    try:
        target_dir = Path(settings.backup_dir)
        name = f"{FILE_PREFIX}{datetime.now().strftime('%Y%m%d-%H%M%S')}{FILE_SUFFIX}"
        try:
            path = create_backup(settings.data_dir, target_dir / name, watch_dir=settings.watch_dir,
                                 exclude_dirs=[settings.backups_dir])
        except Exception as exc:
            _write_status(settings.data_dir, last_error=str(exc)[:300],
                          last_error_at=datetime.now(UTC).isoformat(timespec="seconds"))
            LOGGER.error("Respaldo %s fallido: %s", reason, exc)
            raise
        for old in list_backups(target_dir)[settings.backup_keep:]:
            try:
                Path(old["path"]).unlink()
            except OSError:
                LOGGER.warning("No se pudo borrar el respaldo antiguo %s", old["name"])
        _write_status(settings.data_dir, last_ok=datetime.now(UTC).isoformat(timespec="seconds"),
                      last_path=str(path), last_reason=reason, last_error=None)
        LOGGER.info("Respaldo %s creado: %s", reason, path)
        return path
    finally:
        _run_lock.release()


def backup_due(settings, now: float | None = None) -> bool:
    if not settings.backup_hours:
        return False
    last = read_status(settings.data_dir).get("last_ok")
    if not last:
        return True
    try:
        last_ts = datetime.fromisoformat(last).timestamp()
    except ValueError:
        return True
    return (now or time.time()) - last_ts >= settings.backup_hours * 3600


def start_scheduler(settings, check_every: float = 15 * 60) -> threading.Thread | None:
    """Hilo que crea el respaldo cuando corresponde (revisa cada 15 minutos)."""
    if not settings.backup_hours:
        LOGGER.info("Respaldo automático desactivado (VEXA_BACKUP_HOURS=0).")
        return None

    def loop():
        time.sleep(60)                      # deja arrancar el servidor antes del primer respaldo
        while True:
            try:
                if backup_due(settings):
                    run_backup(settings)
            except Exception:
                pass                        # el error ya quedó en el estado y en el log
            time.sleep(check_every)

    thread = threading.Thread(target=loop, name="vexa-respaldos", daemon=True)
    thread.start()
    return thread
