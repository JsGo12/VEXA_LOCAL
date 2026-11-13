# VEXA Local

Aplicación jurídica local y privada para organizar expedientes y consultar documentos con RAG e IA local (Ollama).

> Prototipo académico: usa documentos ficticios, no expedientes reales ni datos personales.

## Estructura del repositorio

```text
VEXA_LOCAL-Desktop/
├── Codigo/        Aplicación actual (backend, frontend, Electron, scripts, docs)  ← trabaja aquí
├── historico/     Versión anterior y su documentación, solo como referencia
├── run.py         Atajo: ejecuta Codigo/backend/run.py
└── README.md
```

## Versión actual

Todo está en [`Codigo/`](Codigo/):

- [Guía principal: instalación, ejecución, pruebas y estructura](Codigo/README.md)
- [Despliegue en la firma (servidor + PCs de abogados)](Codigo/docs/despliegue.md)
- [Documentación técnica](Codigo/docs/)

Usa Electron, Flask + Waitress, SQLite y Ollama. El backend escucha en `127.0.0.1` (y, opcionalmente, solo en la IP privada de Tailscale); los datos locales se guardan en `%USERPROFILE%\.vexa_local`.

## Historial

- [`historico/README_HISTORICO.md`](historico/README_HISTORICO.md): documentación de la versión inicial.
- [`historico/version_anterior/`](historico/version_anterior/): código de la versión previa (`app.py`, `web_app.py`, `static/`, `templates/`, `desktop/`…). No se ejecuta ni se mantiene.
