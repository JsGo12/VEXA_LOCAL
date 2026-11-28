"""Clave de sesión de Flask (firma de cookies). Es independiente de la clave de cifrado de documentos.

- Si `VEXA_SECRET_KEY` está definida en el entorno o en `.env`, se usa esa.
- Si no, se usa `<VEXA_DATA_DIR>/web_secret.key`, guardada cifrada con el vault (DPAPI en Windows).
  Es el mecanismo de versiones anteriores y se conserva para no invalidar sesiones ni exponer la
  clave en texto plano dentro de una carpeta sincronizada.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

from vexa.security import vault

SECRET_FILE = "web_secret.key"


def _write(path: Path, value: str) -> None:
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    tmp.write_text(vault.enc_text(value), encoding="utf-8")
    os.replace(tmp, path)


def load_session_secret(data_dir: Path, configured: Optional[str] = None) -> str:
    if configured:
        return configured
    path = Path(data_dir) / SECRET_FILE
    if path.exists():
        stored = path.read_text(encoding="utf-8")
        if stored.startswith(vault.TEXT_PREFIX):
            value = vault.dec_text(stored)
            if value.startswith("[contenido ilegible:"):
                raise RuntimeError("No se pudo recuperar la clave de sesión de VEXA con la clave local.")
            return value
        # Clave antigua sin cifrar: se migra sin cambiar su valor (no invalida sesiones).
        _write(path, stored)
        return stored
    value = secrets.token_hex(32)
    _write(path, value)
    return value
