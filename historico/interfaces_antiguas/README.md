# Interfaces antiguas (no activas)

Estas interfaces corresponden a versiones anteriores de VEXA y se conservan solo como referencia
histórica. **La aplicación actual es el backend Flask (`backend/`) con la interfaz de `frontend/`,
abierta por Electron (`desktop/`).**

| Archivo | Qué era |
|---|---|
| `app_tkinter.py` | App de escritorio Tkinter con PIN (usaba `%USERPROFILE%\.vexa_local\config.json`). |
| `main_pywebview.py` + `interface.html` + `static/` | Prototipo con pywebview. |

Antes estaban en `Codigo/legacy/`. Usaban funciones del motor RAG (`procesar_documentos`,
`consultar_llm`…) que la aplicación actual ya no tiene, así que **ya no se pueden ejecutar** con el
código de `Codigo/`; para verlas funcionar, usa una versión anterior del repositorio (git). Además
**no aplicaban los permisos, la auditoría ni el cifrado** de la versión actual. Dependencias propias:
`requirements.txt` de esta carpeta.
