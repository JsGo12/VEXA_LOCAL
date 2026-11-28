"""Crea la clave de recuperación de VEXA (copia de vault.key protegida con contraseña).

Ejecútalo en el PC servidor, con la misma cuenta de Windows que usa VEXA, y guarda el archivo en una
USB o disco externo (no en OneDrive ni en el mismo disco). Sin esta clave, si el PC se daña, los
documentos cifrados no se pueden recuperar ni siquiera teniendo los respaldos.

    .\\.venv\\Scripts\\python.exe backend\\scripts\\clave_recuperacion.py E:\\vexa-clave-recuperacion.vexakey

La contraseña no se guarda en ningún lado: anótala en un lugar seguro y separado del archivo.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Codigo/backend

from vexa.config import load_settings  # noqa: E402
from vexa.security import recovery, vault  # noqa: E402
from vexa.services.backups import looks_like_cloud  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crear la clave de recuperación de VEXA")
    parser.add_argument("destino", type=Path, help="archivo a crear, por ejemplo E:\\vexa-clave.vexakey")
    args = parser.parse_args(argv)
    if looks_like_cloud(args.destino):
        parser.error("El destino parece una carpeta sincronizada con la nube. Usa una USB o un disco externo.")
    settings = load_settings()
    vault.configure(settings.data_dir)
    if not (settings.data_dir / "vault.key").is_file():
        parser.error(f"No hay vault.key en {settings.data_dir}: ejecuta esto en el PC servidor.")
    first = getpass.getpass(f"Contraseña nueva (mínimo {recovery.MIN_PASSPHRASE} caracteres): ")
    if first != getpass.getpass("Repite la contraseña: "):
        parser.error("Las contraseñas no coinciden.")
    try:
        info = recovery.export_recovery(args.destino, first, data_dir=settings.data_dir)
    except recovery.RecoveryError as exc:
        parser.error(str(exc))
    print(f"Clave de recuperación creada: {args.destino}")
    print(f"Huella: {info['fingerprint']} (aparece en Administración > Respaldos)")
    print("Guarda el archivo fuera de este PC y la contraseña en un lugar distinto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
