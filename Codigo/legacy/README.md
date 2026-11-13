# Interfaces antiguas (no activas)

Estas interfaces corresponden a versiones anteriores de VEXA y se conservan solo como referencia
histórica. **La aplicación actual es el backend Flask (`backend/`) con la interfaz de `frontend/`,
abierta por Electron (`desktop/`).**

| Archivo | Qué era |
|---|---|
| `app_tkinter.py` | App de escritorio Tkinter con PIN (usaba `%USERPROFILE%\.vexa_local\config.json`). |
| `main_pywebview.py` + `interface.html` + `static/` | Prototipo con pywebview. |

Ambas reutilizan el motor RAG actual (`backend/vexa/rag/core.py`) mediante una ruta de importación,
pero **no aplican los permisos, la auditoría ni el cifrado** de la versión actual: no las uses con
documentos reales. Dependencias propias: `legacy/requirements.txt`.
