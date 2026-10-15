"""Cifrado en reposo (Fernet/AES) para documentos y textos guardados en disco.

La clave vive en ~/.vexa_local/vault.key. En Windows se protege con DPAPI (queda atada a la cuenta
de usuario de Windows); en otros sistemas se guarda con permisos 600. Los archivos antiguos sin
cifrar se siguen leyendo con normalidad (lectura transparente).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

LOGGER = logging.getLogger(__name__)
MAGIC = b"VEXAENC1"
TEXT_PREFIX = "enc:"
_lock = threading.Lock()
_fernet = None
_dir: Path | None = None


def configure(data_dir) -> None:
    global _dir, _fernet
    _dir, _fernet = Path(data_dir), None


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


def _get() -> Fernet:
    global _fernet
    with _lock:
        if _fernet is not None:
            return _fernet
        carpeta = _dir or (Path.home() / ".vexa_local")
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / "vault.key"
        if ruta.exists():
            raw = ruta.read_bytes()
            key = _dpapi(raw[6:], False) if raw.startswith(b"DPAPI:") else raw
        else:
            key = Fernet.generate_key()
            raw = key
            if sys.platform == "win32":
                try:
                    raw = b"DPAPI:" + _dpapi(key, True)
                except Exception:
                    LOGGER.warning("No se pudo proteger la clave con DPAPI; se guarda sin envoltorio.")
            ruta.write_bytes(raw)
            try:
                os.chmod(ruta, 0o600)
            except OSError:
                pass
        _fernet = Fernet(key)
        return _fernet


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
