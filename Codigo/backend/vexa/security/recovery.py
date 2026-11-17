"""Clave de recuperación: copia de vault.key protegida con una contraseña, para guardar fuera del PC.

Sin vault.key los documentos cifrados no se pueden leer. vault.key está protegida con DPAPI (atada a la
cuenta de Windows del servidor): si el PC se daña o se reinstala Windows, esa protección impide usarla.
La clave de recuperación permite restaurar un respaldo en otro equipo o cuenta.

- Se crea SOLO desde la línea de comandos del servidor (backend/scripts/clave_recuperacion.py), nunca
  desde la web.
- La clave se cifra con Fernet usando una clave derivada de la contraseña con scrypt (n=2^15, r=8, p=1).
- En la carpeta de datos solo se anota la fecha y la huella (recuperacion.json), nunca la clave.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from vexa.security import vault

MAGIC = b"VEXAKEY1"
SALT_BYTES = 16
MIN_PASSPHRASE = 12
STATUS_FILE = "recuperacion.json"


class RecoveryError(ValueError):
    """Clave de recuperación inválida, contraseña incorrecta o archivo dañado."""


def _derive(passphrase: str, salt: bytes) -> bytes:
    raw = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def export_recovery(destination, passphrase: str, data_dir=None) -> dict:
    """Escribe la clave de recuperación en `destination` (no sobrescribe). Devuelve fecha y huella."""
    if len(passphrase) < MIN_PASSPHRASE:
        raise RecoveryError(f"La contraseña debe tener al menos {MIN_PASSPHRASE} caracteres.")
    dest = Path(destination)
    if dest.exists():
        raise RecoveryError(f"Ya existe un archivo en {dest}; elige otro nombre.")
    key = vault.key_bytes()
    salt = secrets.token_bytes(SALT_BYTES)
    blob = MAGIC + salt + Fernet(_derive(passphrase, salt)).encrypt(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    info = {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fingerprint": vault.key_fingerprint(key)}
    if data_dir is not None:
        (Path(data_dir) / STATUS_FILE).write_text(json.dumps(info), encoding="utf-8")
    return info


def load_recovery(path, passphrase: str) -> bytes:
    """Devuelve la clave del vault guardada en el archivo de recuperación."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise RecoveryError(f"No se pudo leer la clave de recuperación: {exc}") from exc
    if not raw.startswith(MAGIC) or len(raw) <= len(MAGIC) + SALT_BYTES:
        raise RecoveryError("El archivo no es una clave de recuperación de VEXA.")
    salt = raw[len(MAGIC):len(MAGIC) + SALT_BYTES]
    try:
        key = Fernet(_derive(passphrase, salt)).decrypt(raw[len(MAGIC) + SALT_BYTES:])
        Fernet(key)
    except (InvalidToken, ValueError) as exc:
        raise RecoveryError("La contraseña no es correcta o el archivo está dañado.") from exc
    return key


def status(data_dir) -> dict:
    """Estado para el panel: si se exportó y si corresponde a la clave actual (sin exponerla)."""
    path = Path(data_dir) / STATUS_FILE
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"exported": False}
    try:
        current = vault.key_fingerprint()
    except Exception:
        current = None
    return {"exported": True, "exported_at": info.get("exported_at"),
            "matches": bool(current and info.get("fingerprint") == current)}
