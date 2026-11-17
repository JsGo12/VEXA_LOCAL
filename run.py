"""Atajo desde la raíz del repositorio al servidor real de VEXA (Codigo/backend/run.py).

    python run.py            Waitress (127.0.0.1 y, si TAILSCALE_ENABLED=true, la IP de Tailscale)
    python run.py --check    Valida Codigo/.env sin iniciar nada

La versión anterior de este archivo importaba `VexaApp.web_app` (ya no existe) y escuchaba en
0.0.0.0:8080, exponiendo VEXA a toda la red local. La configuración ahora vive en Codigo/.env.
"""
import runpy
import sys
from pathlib import Path

backend_run = Path(__file__).resolve().parent / "Codigo" / "backend" / "run.py"
venv_python = backend_run.parents[1] / ".venv" / "Scripts" / "python.exe"
if not venv_python.exists():
    print("Falta el entorno de Codigo. Ejecuta en Codigo:  python -m venv .venv  y  "
          ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt", file=sys.stderr)
sys.argv[0] = str(backend_run)
runpy.run_path(str(backend_run), run_name="__main__")
