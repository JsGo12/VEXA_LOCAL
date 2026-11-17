# Arquitectura de VEXA Local

## Visión general

```text
 Electron (desktop/electron/main.js)          Navegador de un dispositivo Tailscale
        │ http://127.0.0.1:<puerto aleatorio>          │ http://100.x.y.z:5000 (opcional)
        ▼                                              ▼
 ┌──────────────────────── Waitress (vexa.server) ─────────────────────────┐
 │ RemoteAddressFilter: solo loopback (+ rango Tailscale si está activo)   │
 │ Flask app (vexa.create_app)                                             │
 │   security.http   CSRF, cabeceras (CSP), carga de g.user                │
 │   permissions     decoradores y guardas → permissions.policy            │
 │   routes/*        auth, admin, access, audit_log, cases, assistant, …   │
 │   services/*      users, cases, indexing, assistant, audit, watcher     │
 │   rag/*           core, hybrid, stages, firm, formats, model_select     │
 │   database/*      conexión, migraciones, store (caché y chat)           │
 └───────────┬────────────────────────────┬───────────────────────────────┘
             │ SQLite + archivos cifrados  │ HTTP local
             ▼                             ▼
   %USERPROFILE%\.vexa_local         Ollama en 127.0.0.1:11434
```

Todo el procesamiento documental y de IA ocurre en el equipo servidor. `OLLAMA_HOST` solo admite direcciones de loopback.

## Backend (`backend/vexa`)

| Paquete | Responsabilidad |
|---|---|
| `config/` | Lee `.env` + entorno, valida y produce un `Settings` inmutable. Rechaza `0.0.0.0`, Ollama remoto, etc. |
| `database/` | `connect()` común (FK, WAL, cierre automático), `migrations.py` (esquema versionado con `PRAGMA user_version` y respaldo previo) y `store.py` (caché de fragmentos/embeddings, historial del chat por caso, resúmenes, bloqueo de login). |
| `security/` | `vault.py` (cifrado Fernet; clave en `vault.key` protegida con DPAPI), `session_secret.py` (clave de sesión de Flask, independiente), `http.py` (CSRF, cabeceras), `network.py` (direcciones de escucha, Tailscale, filtro de origen). |
| `permissions/` | `catalog.py` (roles y permisos), `policy.py` (motor de autorización sin Flask) y `__init__.py` (decoradores `login_required`, `permission_required`, guardas `require_case`, `require_document`). |
| `services/` | Lógica de negocio sin presentación: `users`, `cases`, `indexing` (`CaseIndexer`: cachés e indexación de fondo), `assistant` (`FirmAssistant`), `audit`, `watcher`, `background`. |
| `rag/` | Motor RAG: `core` (Chunk, BM25, prompt, cliente Ollama), `hybrid` (cláusulas, embeddings, RRF, memoria), `stages` (map-reduce y resúmenes), `firm` (recuperación multi-expediente), `formats` (PDF/OCR, DOCX, XLSX, PPTX, TXT, CSV), `model_select`. |
| `routes/` | Blueprints delgados: validan la petición, llaman a `permissions` y `services`, y devuelven HTML/JSON/NDJSON. |
| `server.py` | Waitress (o el servidor de desarrollo), bloqueo de instancia única y `server.json`. |

Dependencias permitidas (sin ciclos, verificadas por `test_every_backend_module_imports_without_cycles`):

```text
routes → permissions, services, rag, database, security
services → permissions.policy, rag, database, security
permissions → database, services.audit
rag → database.store, security.vault
database, security, config → (solo bibliotecas)
```

### Estado en memoria (`Runtime`)

`create_app()` guarda en `app.extensions["vexa"]` un `Runtime` con `settings`, el `CaseIndexer` y el `FirmAssistant`. No hay variables globales de módulo con estado de la app (salvo la configuración del motor RAG que fija `apply_engine_settings`).

### Flujo del chat por expediente

1. `require_case(case_id, "documents.view")` y `visible_documents()` → solo documentos autorizados.
2. `CaseIndexer.get_index(case_id, rutas_autorizadas)`: clave `(case_id, firma)`; la firma incluye ruta, SHA, tamaño y fecha de cada documento incluido, así que dos usuarios con distinto conjunto autorizado nunca comparten índice.
3. Reformulación de seguimiento, caché de respuestas `(case_id, firma, usuario, pregunta, modelo)`.
4. Pregunta de totalidad → `rag.stages.responder_por_etapas`; si no, búsqueda híbrida + vecinos + límite de contexto → `rag.hybrid.consultar_stream`.
5. Respuesta en NDJSON (`delta`, `progress`, `done`, `error`) y persistencia cifrada en `chat_messages`.

El índice de fondo y el resumen automático usan solo documentos **no restringidos**; el resumen se muestra únicamente a quien ve todos esos documentos.

### Flujo del asistente transversal

1. `assistant.use` + alcance del asistente (`policy.assistant_scope`): casos del alcance de datos cuya vía de acceso está habilitada por `assistant.case_access`, `assistant.team_access` o `assistant.firm_access`.
2. `FirmAssistant.authorized_material()` arma la lista de documentos visibles (aplicando restricciones) y una «ficha» por expediente (metadatos: responsable, fecha límite, resumen).
3. Índice híbrido sobre esos documentos (reutiliza la caché de fragmentos/embeddings en SQLite) con caché por `(usuario, firma)`.
4. `rag.firm.retrieve()` recupera fragmentos y agrega fichas de los expedientes involucrados; `rag.firm.stream_answer()` usa un prompt que exige citar el expediente.
5. Se guardan mensaje y fuentes (`assistant_messages`, `assistant_message_sources`), separados de `chat_messages`. Al leer, cada fuente se vuelve a autorizar: si ya no es visible, la respuesta se oculta.

## Frontend (`frontend/`)

Ver [frontend/README.md](../frontend/README.md). El frontend nunca accede a SQLite: usa rutas HTML del backend y APIs JSON/NDJSON bajo `/api/`.

## Escritorio (`desktop/`)

`main.js` busca primero un servidor VEXA activo (`server.json` + `/health`) y se conecta a él; si no hay, reserva un puerto libre en `127.0.0.1`, ejecuta `backend/run.py` (o `VexaBackend.exe` empaquetado) con `TAILSCALE_ENABLED=false` y espera `/health`. La ventana mantiene `contextIsolation`, `sandbox` y sin `nodeIntegration`, y bloquea navegación fuera del origen local.

## Decisiones relevantes

- **Datos fuera del repositorio** (`%USERPROFILE%\.vexa_local`): la carpeta del proyecto está en OneDrive; guardar ahí la base y los documentos los sincronizaría con la nube.
- **Clave de sesión ≠ clave de documentos**: `VEXA_SECRET_KEY` (o `web_secret.key`) firma cookies; `vault.key` cifra datos. Ninguna se deriva de la otra.
- **El rol no concede datos**: incluso el acceso global del administrador es una concesión explícita (`access_grants` tipo `firm`) creada por la migración 4 para mantener el comportamiento anterior.
