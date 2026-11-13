"""Catálogo de roles y permisos (fuente única de verdad). Ver docs/permisos.md."""
from __future__ import annotations

ROLES = {
    "admin": "Administrador",
    "chief_lawyer": "Abogado/a jefe",
    "lawyer": "Abogado/a",
}

PERMISSIONS = {
    "users.manage": "Crear cuentas, cambiar roles y activar o desactivar usuarios",
    "teams.manage": "Crear equipos y cambiar sus integrantes",
    "cases.manage": "Crear casos, ver su listado y cambiar asignaciones",
    "cases.set_deadline": "Cambiar la fecha límite de los casos",
    "cases.view": "Abrir expedientes dentro de su alcance",
    "documents.view": "Leer y consultar (chat/RAG) documentos dentro de su alcance",
    "documents.download": "Descargar documentos dentro de su alcance",
    "documents.upload": "Agregar documentos a casos dentro de su alcance",
    "cases.update_progress": "Actualizar estado, avance y notas de casos dentro de su alcance",
    "permissions.manage": "Conceder o revocar permisos, alcances y restricciones documentales",
    "assistant.use": "Usar el asistente IA transversal",
    "assistant.case_access": "Asistente: incluir casos asignados o concedidos individualmente",
    "assistant.team_access": "Asistente: incluir casos de sus equipos o de equipos concedidos",
    "assistant.firm_access": "Asistente: incluir casos de su alcance de firma",
    "audit.view": "Ver el registro de auditoría",
}

# Permisos funcionales por rol. Ninguno concede DATOS por sí solo: el alcance sobre expedientes se
# obtiene por asignación (directa o por equipo) o por una concesión explícita en access_grants.
ROLE_PERMISSIONS = {
    "lawyer": frozenset({"cases.view", "documents.view", "documents.download", "cases.update_progress"}),
    "chief_lawyer": frozenset({
        "users.manage", "teams.manage", "cases.manage", "cases.view", "documents.view",
        "documents.download", "documents.upload", "cases.update_progress", "permissions.manage", "assistant.use", "assistant.case_access",
        "assistant.team_access", "assistant.firm_access", "audit.view",
    }),
    # El administrador tiene todos los permisos funcionales; los datos que ve siguen dependiendo de
    # sus concesiones (la `firm` inicial es revocable).
    "admin": frozenset({
        "users.manage", "teams.manage", "cases.manage", "cases.set_deadline", "cases.view", "documents.view",
        "documents.download", "documents.upload", "cases.update_progress", "permissions.manage", "assistant.use",
        "assistant.case_access", "assistant.team_access", "assistant.firm_access", "audit.view",
    }),
}

MANAGEMENT_PERMISSIONS = frozenset({"users.manage", "teams.manage", "cases.manage"})
SCOPE_TYPES = {"firm": "Toda la firma", "team": "Equipo", "case": "Caso"}

# Roles que puede asignar quien no es administrador (evita autopromociones en cadena).
ROLES_ASSIGNABLE_BY = {
    "admin": frozenset(ROLES),
    "chief_lawyer": frozenset({"lawyer"}),
}
