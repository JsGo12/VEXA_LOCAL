"""Cifrado en reposo (Fernet/AES) para documentos y textos guardados en disco.

La clave vive en ~/.vexa_local/vault.key. En Windows se protege con DPAPI (queda atada a la cuenta
de usuario de Windows); en otros sistemas se guarda con permisos 600. Los archivos antiguos sin
cifrar se siguen leyendo con normalidad (lectura transparente).
"""
from __future__ import annotations

import contextlib
import logging
import os
import secrets
import sys
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

LOGGER = logging.getLogger(__name__)
MAGIC = b"VEXAENC1"
TEXT_PREFIX = "enc:"
_lock = threading.Lock()
_fernet = None
_key: bytes | None = None
_dir: Path | None = None


def configure(data_dir) -> None:
    global _dir, _fernet, _key
    _dir, _fernet, _key = Path(data_dir), None, None


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    entrada = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    salida = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
        raise OSError("DPAPI falló")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def _unwrap(raw: bytes) -> bytes:
    """Contenido de vault.key -> clave Fernet (descifra con DPAPI si tiene el prefijo)."""
    return _dpapi(raw[6:], False) if raw.startswith(b"DPAPI:") else raw


def _get() -> Fernet:
    global _fernet, _key
    with _lock:
        if _fernet is not None:
            return _fernet
        carpeta = _dir or (Path.home() / ".vexa_local")
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / "vault.key"
        if ruta.exists():
            raw = ruta.read_bytes()
            key = _unwrap(raw)
            if not raw.startswith(b"DPAPI:") and sys.platform == "win32":
                # Se siguen leyendo las claves de versiones anteriores; en Windows, una clave
                # antigua en texto plano se protege con DPAPI en el mismo lugar si DPAPI funciona.
                try:
                    _write_atomic(ruta, b"DPAPI:" + _dpapi(key, True))
                except Exception:
                    LOGGER.warning("No se pudo proteger una clave antigua con DPAPI; se conserva para no perder acceso a los datos.")
        else:
            key = Fernet.generate_key()
            # En Windows las claves nuevas siempre quedan protegidas con DPAPI (nunca en texto plano).
            try:
                _create_atomic(ruta, protected_key_file(key))
            except FileExistsError:
                # A second process created the key while this one prepared it.
                key = _unwrap(ruta.read_bytes())
        _key = key
        _fernet = Fernet(key)
        return _fernet


def key_bytes() -> bytes:
    """Clave actual del vault (solo para exportar la clave de recuperación desde la línea de comandos)."""
    _get()
    return _key


def key_fingerprint(key: bytes | None = None) -> str:
    """Huella corta y no reversible de la clave, para comprobar que una copia corresponde a esta clave."""
    import hashlib
    return hashlib.sha256(key if key is not None else key_bytes()).hexdigest()[:16]


def protected_key_file(key: bytes) -> bytes:
    """Contenido de vault.key para ESTA cuenta (DPAPI en Windows), igual que al crear una clave nueva."""
    Fernet(key)                                   # valida el formato antes de escribir nada
    return b"DPAPI:" + _dpapi(key, True) if sys.platform == "win32" else key


def _write_temp(path: Path, data: bytes) -> Path:
    """Escribe `data` en un archivo temporal junto a `path` (fsync + permisos 0600) y devuelve su ruta.

    Si la escritura falla, borra el temporal incompleto antes de relanzar el error.
    """
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with tmp.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with contextlib.suppress(OSError):
            os.chmod(tmp, 0o600)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _write_atomic(path: Path, data: bytes) -> None:
    """Reemplaza un archivo de clave de forma atómica y limpia el temporal si algo se interrumpe."""
    tmp = _write_temp(path, data)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _create_atomic(path: Path, data: bytes) -> None:
    """Crea la clave una sola vez, aunque dos procesos de VEXA partan al mismo tiempo.

    Lanza FileExistsError si otro proceso la creó primero; en ese caso _get vuelve a leerla.
    """
    tmp = _write_temp(path, data)
    try:
        if sys.platform == "win32":
            # Windows rename is atomic and refuses to replace an existing key.
            os.rename(tmp, path)
        else:
            os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def is_encrypted(datos: bytes) -> bool:
    return datos.startswith(MAGIC)


def encrypt_bytes(datos: bytes) -> bytes:
    return MAGIC + _get().encrypt(datos)


def decrypt_bytes(datos: bytes) -> bytes:
    return _get().decrypt(datos[len(MAGIC):]) if is_encrypted(datos) else datos


def read_bytes(ruta) -> bytes:
    return decrypt_bytes(Path(ruta).read_bytes())


def write_encrypted(ruta, datos: bytes) -> None:
    Path(ruta).write_bytes(encrypt_bytes(datos))


def encrypt_existing(carpeta) -> int:
    """Cifra en el lugar los archivos que aún estén sin cifrar. Devuelve cuántos cifró."""
    n = 0
    for f in Path(carpeta).rglob("*"):
        if f.is_file():
            datos = f.read_bytes()
            if not is_encrypted(datos):
                tmp = f.with_suffix(f.suffix + ".tmp")
                tmp.write_bytes(encrypt_bytes(datos))
                os.replace(tmp, f)
                n += 1
    return n


def enc_text(texto: str) -> str:
    return TEXT_PREFIX + _get().encrypt(texto.encode("utf-8")).decode("ascii")


def dec_text(valor: str) -> str:
    if not valor.startswith(TEXT_PREFIX):
        return valor
    try:
        return _get().decrypt(valor[len(TEXT_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return "[contenido ilegible: clave distinta]"
