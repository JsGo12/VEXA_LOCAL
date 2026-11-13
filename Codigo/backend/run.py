"""Punto de entrada del backend VEXA.

    python run.py            Servidor Waitress (predeterminado; lee ../.env)
    python run.py --dev      Servidor de desarrollo de Flask (solo loopback, nunca en producción)
    python run.py --check    Valida la configuración y muestra dónde escucharía, sin iniciar nada

Electron ejecuta este mismo archivo con VEXA_HOST/VEXA_PORT definidos en el entorno.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vexa.config import ConfigError, load_settings  # noqa: E402
from vexa.security import network  # noqa: E402
from vexa.server import EXIT_CONFIG, serve  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Servidor local de VEXA")
    parser.add_argument("--dev", action="store_true", help="usar el servidor de desarrollo de Flask")
    parser.add_argument("--check", action="store_true", help="validar la configuración y salir")
    args = parser.parse_args(argv)
    if args.check:
        try:
            settings = load_settings()
            listeners = network.listen_addresses(settings)
        except ConfigError as exc:
            print(f"Configuración inválida: {exc}", file=sys.stderr)
            return EXIT_CONFIG
        print("Configuración válida.")
        print("Archivo .env:", settings.env_file or "(no encontrado; se usan valores predeterminados)")
        print("Carpeta de datos:", settings.data_dir)
        print("Escucharía en:", ", ".join(f"http://{h}:{p}" for h, p in listeners))
        print("Ollama:", settings.ollama_host)
        return 0
    return serve(dev=args.dev)


if __name__ == "__main__":
    sys.exit(main())
