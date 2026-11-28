"""Códigos de un solo uso por tiempo (TOTP, RFC 6238) para el doble factor. Solo biblioteca estándar.

Compatible con Google Authenticator, Microsoft Authenticator, Aegis, etc.: SHA-1, 6 dígitos, 30 s.
La clave se muestra para escribirla a mano en la app (sin QR, para no agregar dependencias).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

DIGITS = 6
PERIOD = 30
WINDOW = 1          # acepta el código anterior y el siguiente (relojes algo desfasados)


def new_secret() -> str:
    """Clave aleatoria de 160 bits en base32 (sin '=')."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    clean = secret.replace(" ", "").upper()
    return base64.b32decode(clean + "=" * (-len(clean) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def verify(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int | None:
    """Devuelve el paso de tiempo del código si es válido y no se usó antes; si no, None.

    Guardar el paso devuelto (users.totp_last_step) impide reutilizar el mismo código."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if candidate > last_step and hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def grouped(secret: str) -> str:
    """'ABCD EFGH IJKL …' para copiarla sin errores."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))

