"""Crea una instalación de demostración de VEXA con datos 100 % ficticios (para la presentación).

Siempre en una carpeta de datos NUEVA, nunca en la real: si la carpeta ya tiene datos, no hace nada.

    .\\.venv\\Scripts\\python.exe backend\\scripts\\datos_demo.py C:\\VEXA_demo
    $env:VEXA_DATA_DIR='C:\\VEXA_demo'; .\\.venv\\Scripts\\python.exe backend\\run.py

Todas las cuentas usan la misma contraseña de demostración (se muestra al terminar).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Codigo/backend

from vexa import create_app  # noqa: E402
from vexa.config import load_settings  # noqa: E402
from vexa.database import connect  # noqa: E402
from vexa.services import users as user_service  # noqa: E402

DEMO_PASSWORD = "Demo-VEXA-2026"

# (usuario, nombre, rol)
PEOPLE = [
    ("jefa", "Camila Rojas", "chief_lawyer"),
    ("luis", "Luis Fuentes", "lawyer"),
    ("ana", "Ana Morales", "lawyer"),
    ("pedro", "Pedro Soto", "lawyer"),
]
TEAM = ("Equipo Laboral", ["ana", "pedro"])
SUPERVISED_BY_CHIEF = ["luis", "ana"]


def prepare(data_dir: Path):
    """App de VEXA sobre una carpeta de datos nueva. Devuelve los ajustes."""
    if data_dir.exists() and any(data_dir.iterdir()):
        raise SystemExit(f"{data_dir} ya tiene archivos. Usa una carpeta nueva: los datos de demostración "
                         "nunca se mezclan con datos reales.")
    # Todo dentro de la carpeta nueva, aunque el .env real defina otras rutas (VEXA_DB_PATH, etc.).
    environ = {**os.environ, "VEXA_DATA_DIR": str(data_dir), "VEXA_DB_PATH": str(data_dir / "vexa_web.db"),
               "VEXA_WATCH_DIR": str(data_dir / "carpeta_vigilada"), "VEXA_ADMIN_PASSWORD": DEMO_PASSWORD,
               "VEXA_BACKUP_DIR": str(data_dir.parent / (data_dir.name + "_respaldos"))}
    settings = load_settings(environ)
    create_app(settings)                               # migra la base y crea el administrador
    with connect(settings.db_path) as db:              # demo: nadie debe cambiar la contraseña al entrar
        db.execute("UPDATE users SET must_change_password = 0")
    (data_dir / "credenciales_admin_inicial.txt").unlink(missing_ok=True)
    return settings


def create_people(settings) -> dict[str, int]:
    ids = {}
    for username, name, role in PEOPLE:
        ids[username] = user_service.create_user(settings.db_path, name, username, DEMO_PASSWORD, role)
    with connect(settings.db_path) as db:
        db.execute("UPDATE users SET must_change_password = 0")
        ids["admin"] = db.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()[0]
    name, members = TEAM
    ids["team"] = user_service.create_team(settings.db_path, name, [ids[m] for m in members])
    user_service.set_supervised_lawyers(settings.db_path, ids["jefa"], [ids[m] for m in SUPERVISED_BY_CHIEF])
    return ids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crear datos de demostración de VEXA (ficticios)")
    parser.add_argument("carpeta", type=Path, help="carpeta de datos NUEVA para la demostración")
    args = parser.parse_args(argv)
    settings = prepare(args.carpeta.resolve())
    create_people(settings)
    print(f"Datos de demostración creados en {settings.data_dir}")
    print(f"Usuarios: admin, {', '.join(p[0] for p in PEOPLE)} · contraseña: {DEMO_PASSWORD}")
    print(f"Para usarlos: $env:VEXA_DATA_DIR='{settings.data_dir}'; .\\.venv\\Scripts\\python.exe backend\\run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
