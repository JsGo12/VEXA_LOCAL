"""Quita el doble factor de una cuenta desde el PC servidor (p. ej. si el único administrador perdió el celular).

Requiere acceso al PC servidor y a la carpeta de datos de VEXA, igual que crear la clave de recuperación.
Si hay otro administrador, es mejor hacerlo desde Administración > Usuarios (queda en la auditoría igual).

    .\\.venv\\Scripts\\python.exe backend\\scripts\\quitar_doble_factor.py admin
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Codigo/backend

from vexa.config import load_settings  # noqa: E402
from vexa.database import connect  # noqa: E402
from vexa.services import audit  # noqa: E402
from vexa.services import users as user_service  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Quitar el doble factor de una cuenta de VEXA")
    parser.add_argument("usuario", help="nombre de usuario (el que se escribe al iniciar sesión)")
    args = parser.parse_args(argv)
    settings = load_settings()
    if not settings.db_path.is_file():
        parser.error(f"No se encontró la base de VEXA en {settings.db_path}: ejecuta esto en el PC servidor.")
    with connect(settings.db_path) as db:
        user = db.execute("SELECT id, username, totp_enabled FROM users WHERE username = ?", (args.usuario,)).fetchone()
    if user is None:
        parser.error(f"No existe la cuenta {args.usuario!r}.")
    if not user["totp_enabled"]:
        print(f"La cuenta {user['username']} no tiene doble factor activado.")
        return 0
    user_service.disable_two_factor(settings.db_path, user["id"])
    audit.record("users.2fa_reset", "ok", resource_type="user", resource_id=user["id"],
                 details={"origen": "línea de comandos"}, username="(consola del servidor)", db_path=settings.db_path)
    print(f"Doble factor quitado de {user['username']}. Puede entrar con su contraseña y configurarlo de nuevo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
