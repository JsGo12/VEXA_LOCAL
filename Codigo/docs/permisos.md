# Roles, permisos y precedencia

Fuente de verdad: `backend/vexa/permissions/catalog.py` (catálogo) y `backend/vexa/permissions/policy.py` (motor). Todas las comprobaciones ocurren en el backend; ocultar botones en la interfaz es solo comodidad. Pruebas: `backend/tests/test_permissions.py` y `test_assistant_and_cache.py`.

## Dos capas

1. **Permisos funcionales**: qué acciones puede hacer la persona.
2. **Alcance de datos**: qué expedientes puede ver. **El rol nunca concede datos por sí solo.**

## Permisos

| Permiso | Permite |
|---|---|
| `users.manage` | Crear cuentas, cambiar roles, activar/desactivar |
| `teams.manage` | Crear equipos y cambiar integrantes |
| `cases.manage` | Crear casos, ver el listado de la firma (metadatos) y reasignar |
| `cases.view` | Abrir expedientes de su alcance |
| `documents.view` | Leer y consultar (chat/RAG) documentos de su alcance |
| `documents.download` | Descargar documentos de su alcance |
| `documents.upload` | Agregar documentos a casos de su alcance |
| `cases.update_progress` | Actualizar estado, avance y notas de casos de su alcance |
| `permissions.manage` | Ajustar permisos, alcances y restricciones documentales |
| `assistant.use` | Usar el asistente transversal |
| `assistant.case_access` | El asistente incluye casos asignados o concedidos individualmente |
| `assistant.team_access` | El asistente incluye casos de sus equipos o de equipos concedidos |
| `assistant.firm_access` | El asistente incluye casos de su alcance de firma |
| `audit.view` | Ver la auditoría |

## Política inicial por rol

| Permiso | Abogado/a | Abogado/a jefe | Administrador |
|---|:-:|:-:|:-:|
| `users.manage`, `teams.manage`, `cases.manage` | — | ✔ | ✔ |
| `cases.view`, `documents.view`, `documents.download` | ✔ | ✔ | ✔ |
| `cases.update_progress` | ✔ | ✔ | ✔ |
| `documents.upload` | — | ✔ | ✔ |
| `cases.set_deadline` (cambiar la fecha límite, en Seguimiento) | — | — | ✔ |
| `permissions.manage`, `audit.view` | — | ✔ | ✔ |
| `assistant.use` y `assistant.*_access` | — | ✔ | ✔ |

Alcance de datos inicial:
- **Abogado/a**: casos asignados a su cuenta o a sus equipos.
- **Abogado/a jefe**: igual que un abogado. **No tiene alcance de firma hasta que un administrador se lo conceda** explícitamente (Permisos → Concesiones → «Toda la firma», un equipo o casos concretos). Mientras tanto el asistente solo cubre sus casos asignados.
- **Administrador**: concesión explícita `firm` (creada al instalar o por la migración 4, para conservar el comportamiento anterior). Es revocable.

Los ajustes por usuario (`user_permissions`) conceden o deniegan permisos concretos sobre lo que da el rol; **`deny` siempre gana**.

## Alcance de datos

Un usuario puede ver el caso C si tiene `cases.view` y al menos una vía:

| Vía | Origen |
|---|---|
| `assigned` | `case_assignments.user_id` = usuario |
| `team` | el caso está asignado a un equipo del que es integrante |
| `grant_case` | `access_grants` tipo `case` con ese caso |
| `grant_team` | `access_grants` tipo `team` con el equipo asignado al caso |
| `firm` | `access_grants` tipo `firm` |

El asistente transversal usa el mismo alcance, filtrado por vía: `assigned`/`grant_case` requieren `assistant.case_access`, `team`/`grant_team` requieren `assistant.team_access` y `firm` requiere `assistant.firm_access`.

## Precedencia documental

La primera regla que aplica decide:

1. Sin `documents.view` (o `documents.download` al descargar) → **denegado**.
2. Expediente fuera de su alcance → **denegado**.
3. Regla `deny` del documento para el usuario (`document_acl`) → **denegado**.
4. Documento **restringido** (`documents.restricted = 1`): solo con regla `allow` para el usuario; si no → **denegado**. *La restricción prevalece incluso sobre el alcance de firma.*
5. En otro caso → **permitido**.

Se aplica igual a la apertura del caso, la descarga, el chat por expediente (solo se indexan documentos permitidos) y el asistente.

## Reglas contra la escalada de privilegios

- Nadie puede cambiar sus propios permisos, alcances, rol ni estado.
- Quien no es administrador solo administra cuentas con rol **abogado/a**; solo un administrador crea o modifica administradores y abogados jefe.
- Solo se pueden **conceder** permisos que uno mismo tiene, y alcances dentro del propio alcance (la firma solo la concede quien la tiene).
- Restringir documentos exige `permissions.manage` y que el caso esté en el propio alcance.
- Todo intento denegado queda en la auditoría (`access.denied` o la acción con resultado `denied`).

## Cuentas y sesiones

- Las cuentas creadas por un administrador (o por un abogado jefe) y la del administrador inicial con contraseña generada deben **cambiar su contraseña en el primer inicio de sesión**. Mientras tanto, solo pueden usar la página de cambio de contraseña.
- Cambiar la contraseña propia exige la actual y cierra las demás sesiones de esa cuenta. Una contraseña temporal asignada por un administrador, una desactivación o un cambio de rol también cierran las sesiones abiertas (`users.session_epoch`).

## Cambios de permisos y cachés

La autorización se calcula en **cada petición** (no se guarda en la sesión). Los índices y respuestas en memoria están ligados al conjunto exacto de documentos autorizados (y, en respuestas y asistente, al usuario), por lo que una revocación rige desde la petición siguiente. Las respuestas guardadas que citan documentos o expedientes que el usuario ya no ve se muestran ocultas.
