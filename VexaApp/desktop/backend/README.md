# Backend empaquetado de VEXA

El modo desarrollo usa el Python instalado en el computador. El script `desktop/build.ps1` crea el entorno aislado `.venv` y usa `requirements-build.txt` para instalar las dependencias necesarias para PyInstaller y los extractores de formatos.

El backend guarda sus datos locales en `%USERPROFILE%\.vexa_local`. Electron lo inicia ligado a `127.0.0.1`. Ollama y sus modelos se instalan y ejecutan por separado; no forman parte del paquete de VEXA.

La extracción OCR de PDF escaneados requiere el ejecutable externo Tesseract. Instalar el paquete Python `pytesseract` no instala Tesseract ni sus datos de idioma.
