# Backend empaquetado de VEXA

`desktop/build.ps1` crea el entorno aislado `desktop/backend/.venv`, instala `requirements-build.txt` (dependencias de `backend/requirements.txt` + PyInstaller) y empaqueta `backend/run.py` como `VexaBackend.exe` (modo `--onedir`), incluyendo el paquete `vexa` y `frontend/templates` y `frontend/static`. El archivo `.spec` se regenera en cada compilación y no se versiona.

El backend empaquetado:
- Lee `.env` junto al ejecutable o en `%USERPROFILE%\.vexa_local\.env`.
- Guarda sus datos en `VEXA_DATA_DIR` (por defecto `%USERPROFILE%\.vexa_local`).
- Arranca con Waitress en `127.0.0.1` y el puerto que le asigna Electron.

Ollama y sus modelos se instalan por separado. El OCR de PDF escaneados requiere el ejecutable externo Tesseract (el paquete `pytesseract` no lo instala).
