# Frontend de VEXA

Plantillas Jinja servidas por Flask y recursos estáticos. No contiene lógica de datos: todo pasa por las rutas del backend (`backend/vexa/routes`).

```text
frontend/
├── templates/
│   ├── base.html                 Estructura, navegación según permisos, mensajes
│   ├── login.html, error.html
│   ├── lawyer.html               Mis casos
│   ├── chief.html                Panel del abogado jefe
│   ├── case.html                 Expediente: tarjeta de resumen (abre ventana emergente con resumen, documentos y ZIP), chat amplio y avance
│   ├── assistant.html            Asistente transversal
│   ├── admin.html                Usuarios, equipos, casos y asignaciones
│   ├── _assignment_fields.html   Selector de responsable (parcial)
│   ├── permissions.html          Permisos por persona (grupos, Según rol/Conceder/Denegar, alcances) y por documento (quién lo ve y por qué, reglas, últimas descargas)
│   ├── audit.html                Registro de auditoría en lenguaje claro (backend/vexa/services/audit_view.py)
│   ├── follow_up.html            Panel de seguimiento (estado, avance, semáforo de vencimientos, cambio de fecha límite)
│   ├── messages.html             Bandeja de mensajes del equipo (conversación de cada caso: js/case-messages.js)
│   ├── notifications.html        Notificaciones (campana de la barra superior: js/notifications.js)
│   ├── profile.html              Mi perfil (datos, casos, actividad, permisos y cambio de contraseña)
│   └── password.html             Cambio de contraseña obligatorio
└── static/
    ├── css/  base.css (estilo original) · layout.css (navegación, piezas comunes)
    │         management.css (tablas de administración) · assistant.css · profile.css
    ├── js/   ndjson.js (streaming y CSRF compartidos) · case-chat.js · case-dialog.js · assistant.js · admin.js
    └── img/
```

## Experiencia de uso

- **Tema claro/oscuro**: `js/theme.js` (en `<head>`, sin destello) + `css/theme-light.css` (solo con `html[data-theme="light"]`).
- **Listas de casos**: macro `_case_collection.html` (filtros, orden, vista tarjetas/tabla) + `js/case-collection.js`. Las ventanas de cada caso van fuera de las tarjetas.
- **Subidas**: `js/upload.js` convierte cualquier `<input type=file>` en zona de arrastre con barra de progreso; envía `X-Requested-With: vexa-upload` y el backend responde `{"redirect": …}` (`routes/cases.upload_reply`).
- **Exportar**: `/admin/seguimiento/exportar.xlsx`, `/admin/audit/exportar.xlsx` (filtros actuales) y botón Imprimir/PDF (`js/print.js`, estilos `@media print`).
- **Celular**: tablas con clase `responsive-table` y `data-label` en cada `<td>` se muestran como tarjetas bajo 760 px.
- Ojo: si un elemento con `display` propio debe ocultarse con `hidden`, agrega una regla `[hidden] { display: none }` para él.

## Reglas

- **Sin scripts ni estilos en línea**: la CSP es `script-src 'self'; style-src 'self'`. Los datos que necesita el JS (URLs) se pasan con atributos `data-*`; el token CSRF va en `<meta name="csrf-token">` o en campos ocultos.
- Insertar texto siempre con `textContent`.
- Ventanas emergentes: `<dialog id=…>` + botón `data-open-dialog="id"` y botones `data-close-dialog` (`case-dialog.js`). Botones de acción: clases `action-btn`, `action-btn-primary`, `action-btn-ghost`.
- Subir documentos admite `next=admin|seguimiento` para volver a ese panel (lista fija, sin redirecciones abiertas).
- Los botones se ocultan según `can('permiso')`, pero la autorización real está en el backend.
- Las respuestas de IA llegan como NDJSON (`application/x-ndjson`): eventos `status`, `delta`, `progress`, `done` (con `sources`) y `error`. `Vexa.readNdjson` los procesa.

## APIs usadas

| Vista | Endpoints |
|---|---|
| Avance y documentos | `POST /case/<id>/progress` (estado/porcentaje), `POST /case/<id>/notes` (nota del abogado), `POST /case/<id>/documents` (multipart), `GET /case/<id>/expediente.zip` |
| Administración | `POST /admin/users/<id_jefe>/lawyers` (abogados a cargo; solo administrador) |
| Perfil | `GET/POST /account` (nombre visible), `POST /account/password` (con `next=profile`) |
| Seguimiento | `POST /admin/cases/<id>/due` (formulario, permiso `cases.set_deadline`) |
| Expediente | `POST /api/case/<id>/chat`, `GET /api/case/<id>/history`, `/status`, `/summary`, `GET /api/ollama/status` |
| Asistente | `GET/POST /api/assistant/conversations`, `GET …/<id>/messages`, `POST …/<id>/ask`, `POST …/<id>/delete`, `GET /api/assistant/scope` |

Las fuentes del asistente incluyen `case_id`, `case_label`, `document_id`, `label`, `page_start`, `page_end` y `downloadable`; la vista enlaza el expediente y, si procede, la descarga.
