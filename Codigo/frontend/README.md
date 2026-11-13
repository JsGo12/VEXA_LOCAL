# Frontend de VEXA

Plantillas Jinja servidas por Flask y recursos estáticos. No contiene lógica de datos: todo pasa por las rutas del backend (`backend/vexa/routes`).

```text
frontend/
├── templates/
│   ├── base.html                 Estructura, navegación según permisos, mensajes
│   ├── login.html, error.html
│   ├── lawyer.html               Mis casos
│   ├── chief.html                Panel del abogado jefe
│   ├── case.html                 Expediente + chat individual
│   ├── assistant.html            Asistente transversal
│   ├── admin.html                Usuarios, equipos, casos y asignaciones
│   ├── _assignment_fields.html   Selector de responsable (parcial)
│   ├── permissions.html          Permisos, alcances y restricciones documentales
│   ├── audit.html                Registro de auditoría
│   ├── follow_up.html            Panel de seguimiento (estado, avance, semáforo de vencimientos, cambio de fecha límite)
│   └── password.html             Cambio de contraseña propia
└── static/
    ├── css/  base.css (estilo original) · layout.css (navegación, piezas comunes)
    │         management.css (tablas de administración) · assistant.css
    ├── js/   ndjson.js (streaming y CSRF compartidos) · case-chat.js · assistant.js · admin.js
    └── img/
```

## Reglas

- **Sin scripts ni estilos en línea**: la CSP es `script-src 'self'; style-src 'self'`. Los datos que necesita el JS (URLs) se pasan con atributos `data-*`; el token CSRF va en `<meta name="csrf-token">` o en campos ocultos.
- Insertar texto siempre con `textContent`.
- Los botones se ocultan según `can('permiso')`, pero la autorización real está en el backend.
- Las respuestas de IA llegan como NDJSON (`application/x-ndjson`): eventos `status`, `delta`, `progress`, `done` (con `sources`) y `error`. `Vexa.readNdjson` los procesa.

## APIs usadas

| Vista | Endpoints |
|---|---|
| Avance y documentos | `POST /case/<id>/progress` (formulario), `POST /case/<id>/documents` (multipart) |
| Seguimiento | `POST /admin/cases/<id>/due` (formulario, permiso `cases.set_deadline`) |
| Expediente | `POST /api/case/<id>/chat`, `GET /api/case/<id>/history`, `/status`, `/summary`, `GET /api/ollama/status` |
| Asistente | `GET/POST /api/assistant/conversations`, `GET …/<id>/messages`, `POST …/<id>/ask`, `POST …/<id>/delete`, `GET /api/assistant/scope` |

Las fuentes del asistente incluyen `case_id`, `case_label`, `document_id`, `label`, `page_start`, `page_end` y `downloadable`; la vista enlaza el expediente y, si procede, la descarga.
