"""Respaldo y restauración de VEXA desde la línea de comandos.

    python backend\\scripts\\backup_vexa.py create E:\\RespaldosVEXA\\vexa.vexabackup
    python backend\\scripts\\backup_vexa.py restore archivo.vexabackup [--target CARPETA] [--replace]
    python backend\\scripts\\backup_vexa.py restore archivo.vexabackup --clave-recuperacion E:\\vexa-clave.vexakey

El servidor ya crea respaldos automáticos (VEXA_BACKUP_*). La lógica vive en vexa/services/backups.py;
este script la expone para restaurar (con VEXA detenido) o para respaldos manuales.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Codigo/backend

from vexa.config import load_settings  # noqa: E402
from vexa.security import recovery, vault  # noqa: E402
from vexa.services.backups import (MAGIC, MAGIC_V1, BackupError, _extract_validated,  # noqa: E402,F401
                                   create_backup, restore_backup)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Respaldo cifrado local de VEXA")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="crear un respaldo")
    create.add_argument("destination", type=Path)
    restore = commands.add_parser("restore", help="restaurar un respaldo (con VEXA detenido)")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target", type=Path, default=None,
                         help="carpeta de datos de destino (predeterminado: VEXA_DATA_DIR)")
    restore.add_argument("--replace", action="store_true", help="mover los datos actuales y restaurar")
    restore.add_argument("--clave-recuperacion", type=Path, default=None, dest="recovery",
                         help="archivo de clave de recuperación (para restaurar en otro equipo o cuenta)")
    args = parser.parse_args(argv)
    settings = load_settings()
    vault.configure(settings.data_dir)
    try:
        if args.command == "create":
            path = create_backup(settings.data_dir, args.destination, watch_dir=settings.watch_dir)
            print(f"Respaldo cifrado creado: {path}")
        else:
            key = None
            if args.recovery:
                key = recovery.load_recovery(args.recovery, getpass.getpass("Contraseña de la clave de recuperación: "))
            path = restore_backup(args.backup, args.target or settings.data_dir, replace=args.replace,
                                  recovery_key=key)
            print(f"Datos restaurados en: {path}")
        return 0
    except (BackupError, recovery.RecoveryError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
