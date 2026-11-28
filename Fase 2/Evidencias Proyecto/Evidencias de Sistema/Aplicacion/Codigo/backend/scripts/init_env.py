"""Crea `Codigo/.env` a partir de `.env.example` de forma segura y explícita.

    python backend\\scripts\\init_env.py                       # crea .env si no existe
    python backend\\scripts\\init_env.py --generate-secret-key # además genera VEXA_SECRET_KEY

- Nunca sobrescribe un `.env` existente (para cambiarlo, edítalo a mano).
- Nunca imprime secretos.
- No toca la clave de cifrado de documentos (`vault.key`): esa la crea y protege VEXA con DPAPI.
- Sin --generate-secret-key, VEXA_SECRET_KEY queda vacía y VEXA usa `web_secret.key` cifrada con
  DPAPI, que es la opción recomendada en Windows (el .env queda en texto plano en el disco).
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def build_env(example: str, generate_secret: bool) -> str:
    lines = []
    for line in example.splitlines():
        if generate_secret and line.startswith("VEXA_SECRET_KEY="):
            line = "VEXA_SECRET_KEY=" + secrets.token_urlsafe(48)
        lines.append(line)
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inicializa el archivo .env de VEXA")
    parser.add_argument("--generate-secret-key", action="store_true",
                        help="generar VEXA_SECRET_KEY (útil fuera de Windows, sin DPAPI)")
    parser.add_argument("--target", type=Path, default=PROJECT / ".env")
    args = parser.parse_args(argv)
    example = PROJECT / ".env.example"
    if args.target.exists():
        print(f"{args.target} ya existe; no se modifica.")
        return 0
    content = build_env(example.read_text(encoding="utf-8"), args.generate_secret_key)
    fd = os.open(args.target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    print(f"Creado {args.target}" + (" con una VEXA_SECRET_KEY nueva." if args.generate_secret_key else "."))
    print("Revisa los valores y no lo subas a Git (está en .gitignore).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
