# Migraciones de la base de datos

VEXA usa SQLite (`vexa_web.db`). El esquema se versiona con `PRAGMA user_version` y lo aplica `backend/vexa/database/migrations.py` cada vez que arranca el backend.

## Cómo funciona

1. Si la base ya tenía datos y hay migraciones pendientes, se crea **antes** una copia consistente con la API de respaldo de SQLite en `<VEXA_DATA_DIR>\backups\vexa_web-antes-de-migrar-v<N>-<fecha>.db`.
2. Se crea el esquema base con `CREATE TABLE IF NOT EXISTS` (idéntico al de la versión anterior, así una base existente no cambia).
3. Cada migración pendiente se ejecuta en su propia transacción (`BEGIN IMMEDIATE` … `COMMIT`). Si falla, se revierte y la base queda en la versión previa; el backend no arranca.
4. `store.init()` crea las tablas de caché e historial (idempotente).

## Migraciones

| Versión | Cambio | Datos existentes |
|---|---|---|
| 1 | Agrega `cases.summary` si falta | Sin pérdida (columna con valor `''`). |
| 2 | Amplía `users.role` para admitir `chief_lawyer` | SQLite no permite cambiar un `CHECK`: se reconstruye `users` copiando todas las filas con sus mismos `id`, se verifica el número de filas y `PRAGMA foreign_key_check`. |
| 3 | Tablas `user_permissions`, `access_grants`, `document_acl`, `audit_log`, `assistant_conversations`, `assistant_messages`, `assistant_message_sources`; columna `documents.restricted` | Solo agrega. |
| 4 | Concede alcance `firm` a los administradores existentes | Conserva el acceso que antes tenían por rol, ahora explícito y revocable. |
| 5 | `cases.status` y `cases.progress`, tabla `case_updates` (notas cifradas), `users.must_change_password` y `users.session_epoch` | Los casos existentes quedan «En curso» con 0 % (lo que mostraba la interfaz anterior); los usuarios existentes no tienen cambio de contraseña pendiente. |

Ninguna migración elimina usuarios, casos, asignaciones, documentos, historial ni claves. La clave de cifrado (`vault.key`) y los archivos cifrados no se tocan.

## Verificación realizada

La secuencia se probó sobre una **copia** de una base real (sin modificar la original): se conservaron todas las filas de `users`, `cases`, `case_assignments`, `documents`, `chat_messages`, `doc_chunks` y `case_summaries`; `PRAGMA integrity_check` = `ok`; sin problemas de claves foráneas. Pruebas automáticas: `test_legacy_database_is_migrated_without_losing_data`, `test_failed_migration_rolls_back`.

## Agregar una migración

1. Escribe una función `_mN_descripcion(db)` idempotente (comprueba antes de alterar). No uses `executescript` dentro de la migración: hace `COMMIT` implícito; usa `_run_script`.
2. Añádela al final de `MIGRATIONS` con el número siguiente.
3. Agrega una prueba que parta de una base con el esquema anterior y datos.

## Revertir

Cierra VEXA y reemplaza `vexa_web.db` por el respaldo `backups\vexa_web-antes-de-migrar-…db` (renombrándolo). Borra también `vexa_web.db-wal` y `vexa_web.db-shm` si existen. La versión anterior del código ignora las tablas nuevas.
