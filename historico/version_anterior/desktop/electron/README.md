# VEXA Desktop (Electron)

Esta carpeta contiene la ventana de escritorio. Electron inicia el backend Flask en un puerto libre ligado exclusivamente a `127.0.0.1`, espera `/health` y luego carga la interfaz. Al cerrar la app, detiene el proceso Python.

## Desarrollo

Requisitos: Node.js con npm y Python instalado con las dependencias de VEXA.

Desde la raíz del proyecto:

```powershell
python -m pip install -r requirements.txt
Set-Location .\desktop\electron
npm install
npm start
```

Si Python no se encuentra en `PATH`, definir `VEXA_PYTHON` con la ruta al ejecutable de Python antes de ejecutar Electron.

## Instalador de Windows

Desde la raíz, ejecutar:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1
```

El script crea un entorno aislado para compilar el backend con PyInstaller y luego genera un instalador NSIS en `desktop/electron/release/`. El equipo donde se instale VEXA debe tener Ollama y el modelo `llama3.2:1b`; el instalador no incluye ese modelo de IA.

## Seguridad local

La ventana mantiene `contextIsolation` y `sandbox` habilitados, y `nodeIntegration` deshabilitado. El servidor Flask queda ligado a `127.0.0.1`; el navegador de Electron no puede navegar fuera del origen local del backend.
