"""Motor de autorización (sin Flask): denegación por defecto y precedencia documentada.

Permisos funcionales (qué acciones puede hacer):
    efectivos = permisos del rol
                + overrides 'allow' de user_permissions
                - overrides 'deny'  de user_permissions      (deny siempre gana)

Alcance de datos (qué expedientes puede ver), unión de:
    assigned    caso asignado directamente al usuario
    team        caso asignado a un equipo del que es integrante
    grant_case  concesión explícita de ese caso         (access_grants scope_type='case')
    grant_team  concesión explícita de un equipo         (access_grants scope_type='team')
    firm        concesión explícita de toda la firma     (access_grants scope_type='firm')
El rol nunca concede alcance de datos por sí mismo.

Acceso a un documento (en este orden; la primera regla que aplica decide):
    1. Sin documents.view (o documents.download para descargar)  -> DENEGADO
    2. El expediente no está en su alcance                       -> DENEGADO
    3. document_acl 'deny' para el usuario                       -> DENEGADO
    4. Documento restringido (documents.restricted = 1):
         con document_acl 'allow' para el usuario -> PERMITIDO; si no -> DENEGADO
       (la restricción prevalece incluso sobre el alcance 'firm')
    5. En otro caso                                              -> PERMITIDO
"""
from __future__ import annotations

import sqlite3
from typing import Dict, Iterable, List, Mapping, Optional, Set

from vexa.permissions.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES_ASSIGNABLE_BY

ASSISTANT_PATH_PERMISSION = {
    "assigned": "assistant.case_access",
    "grant_case": "assistant.case_access",
    "team": "assistant.team_access",
    "grant_team": "assistant.team_access",
    "firm": "assistant.firm_access",
}


def _uid(user) -> int:
    return int(user["id"])


# -------------------------------------------------------------- permisos funcionales
def permission_overrides(db: sqlite3.Connection, user_id: int) -> Dict[str, str]:
    rows = db.execute("SELECT permission, effect FROM user_permissions WHERE user_id = ?", (user_id,)).fetchall()
    return {row["permission"]: row["effect"] for row in rows}


def effective_permissions(db: sqlite3.Connection, user) -> Set[str]:
    if user is None:
        return set()
    granted = set(ROLE_PERMISSIONS.get(user["role"], frozenset()))
    overrides = permission_overrides(db, _uid(user))
    granted |= {p for p, e in overrides.items() if e == "allow" and p in PERMISSIONS}
    granted -= {p for p, e in overrides.items() if e == "deny"}
    return granted


def has_permission(db: sqlite3.Connection, user, permission: str) -> bool:
    return permission in effective_permissions(db, user)


# ------------------------------------------------------------------ alcance de datos
def case_scope(db: sqlite3.Connection, user) -> Dict[int, Set[str]]:
    """{case_id: {vías de acceso}} para todos los expedientes del alcance del usuario."""
    if user is None:
        return {}
    uid = _uid(user)
    scope: Dict[int, Set[str]] = {}

    def add(rows: Iterable, via: str) -> None:
        for row in rows:
            if row[0] is not None:
                scope.setdefault(int(row[0]), set()).add(via)

    add(db.execute("SELECT case_id FROM case_assignments WHERE user_id = ?", (uid,)), "assigned")
    add(db.execute("""SELECT a.case_id FROM case_assignments a
                      JOIN team_members m ON m.team_id = a.team_id WHERE m.user_id = ?""", (uid,)), "team")
    add(db.execute("""SELECT g.scope_id FROM access_grants g JOIN cases c ON c.id = g.scope_id
                      WHERE g.user_id = ? AND g.scope_type = 'case'""", (uid,)), "grant_case")
    add(db.execute("""SELECT a.case_id FROM case_assignments a
                      JOIN access_grants g ON g.scope_type = 'team' AND g.scope_id = a.team_id
                      WHERE g.user_id = ?""", (uid,)), "grant_team")
    if db.execute("SELECT 1 FROM access_grants WHERE user_id = ? AND scope_type = 'firm'", (uid,)).fetchone():
        add(db.execute("SELECT id FROM cases"), "firm")
    return scope


def case_paths(db: sqlite3.Connection, user, case_id: int) -> Set[str]:
    return case_scope(db, user).get(int(case_id), set())


def can_view_case(db: sqlite3.Connection, user, case_id: int) -> bool:
    return has_permission(db, user, "cases.view") and bool(case_paths(db, user, case_id))


def has_firm_scope(db: sqlite3.Connection, user) -> bool:
    return db.execute("SELECT 1 FROM access_grants WHERE user_id = ? AND scope_type = 'firm'",
                      (_uid(user),)).fetchone() is not None


# ---------------------------------------------------------------------- documentos
def _document_rule(db: sqlite3.Connection, user_id: int, document) -> bool:
    acl = db.execute("SELECT effect FROM document_acl WHERE document_id = ? AND user_id = ?",
                     (document["id"], user_id)).fetchone()
    if acl is not None and acl["effect"] == "deny":
        return False
    if document["restricted"]:
        return acl is not None and acl["effect"] == "allow"
    return True


def document_allowed(db: sqlite3.Connection, user, document, permission: str = "documents.view") -> bool:
    if user is None or document is None:
        return False
    if not has_permission(db, user, permission):
        return False
    if not case_paths(db, user, document["case_id"]):
        return False
    return _document_rule(db, _uid(user), document)


def visible_documents(db: sqlite3.Connection, user, case_id: int) -> List[sqlite3.Row]:
    """Documentos del caso que el usuario puede leer (vacío si no tiene documents.view)."""
    if not has_permission(db, user, "documents.view") or not case_paths(db, user, case_id):
        return []
    rows = db.execute("SELECT * FROM documents WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    uid = _uid(user)
    return [row for row in rows if _document_rule(db, uid, row)]


def unrestricted_documents(db: sqlite3.Connection, case_id: int) -> List[sqlite3.Row]:
    """Documentos sin restricción: base común para el índice de fondo y el resumen automático."""
    return db.execute("SELECT * FROM documents WHERE case_id = ? AND restricted = 0 ORDER BY id",
                      (case_id,)).fetchall()


# ------------------------------------------------------------- asistente transversal
def assistant_scope(db: sqlite3.Connection, user) -> Dict[int, Set[str]]:
    """Expedientes que el asistente puede consultar: alcance de datos filtrado por assistant.*."""
    perms = effective_permissions(db, user)
    if "assistant.use" not in perms or "documents.view" not in perms:
        return {}
    result: Dict[int, Set[str]] = {}
    for case_id, vias in case_scope(db, user).items():
        allowed = {v for v in vias if ASSISTANT_PATH_PERMISSION.get(v) in perms}
        if allowed:
            result[case_id] = allowed
    return result


# ------------------------------------------------------ administración sin escalada
class PolicyError(PermissionError):
    """Operación de administración no permitida; el mensaje es apto para mostrar."""


def _target(db: sqlite3.Connection, target_id: int):
    row = db.execute("SELECT id, name, username, role, active FROM users WHERE id = ?", (target_id,)).fetchone()
    if row is None:
        raise PolicyError("El usuario indicado no existe.")
    return row


def check_can_manage_user(db: sqlite3.Connection, actor, target_id: int):
    """Nadie se administra a sí mismo; quien no es admin solo administra cuentas de abogado."""
    target = _target(db, target_id)
    if int(target["id"]) == _uid(actor):
        raise PolicyError("No puedes modificar tus propios permisos, rol o estado.")
    if actor["role"] != "admin" and target["role"] != "lawyer":
        raise PolicyError("Solo un administrador puede modificar cuentas de administración o de abogado jefe.")
    return target


def check_role_change(db: sqlite3.Connection, actor, target_id: int, new_role: str):
    if not has_permission(db, actor, "users.manage"):
        raise PolicyError("No tienes permiso para administrar usuarios.")
    target = check_can_manage_user(db, actor, target_id)
    if new_role not in ROLES_ASSIGNABLE_BY.get(actor["role"], frozenset()):
        raise PolicyError("No puedes asignar ese rol.")
    return target


def check_permission_override(db: sqlite3.Connection, actor, target_id: int, permission: str, effect: str):
    if not has_permission(db, actor, "permissions.manage"):
        raise PolicyError("No tienes permiso para administrar permisos.")
    if permission not in PERMISSIONS or effect not in {"allow", "deny", "clear"}:
        raise PolicyError("Permiso o efecto no válido.")
    target = check_can_manage_user(db, actor, target_id)
    if effect == "allow" and not has_permission(db, actor, permission):
        raise PolicyError("Solo puedes conceder permisos que tú mismo tienes.")
    return target


def check_scope_grant(db: sqlite3.Connection, actor, target_id: int, scope_type: str, scope_id: Optional[int]):
    if not has_permission(db, actor, "permissions.manage"):
        raise PolicyError("No tienes permiso para administrar permisos.")
    target = check_can_manage_user(db, actor, target_id)
    actor_scope = case_scope(db, actor)
    if scope_type == "firm":
        if not has_firm_scope(db, actor):
            raise PolicyError("Solo quien tiene alcance de firma puede concederlo.")
    elif scope_type == "team":
        if db.execute("SELECT 1 FROM teams WHERE id = ?", (scope_id,)).fetchone() is None:
            raise PolicyError("El equipo no existe.")
        member = db.execute("SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?",
                            (scope_id, _uid(actor))).fetchone()
        granted = db.execute("SELECT 1 FROM access_grants WHERE user_id = ? AND scope_type = 'team' AND scope_id = ?",
                             (_uid(actor), scope_id)).fetchone()
        if not (has_firm_scope(db, actor) or member or granted):
            raise PolicyError("Solo puedes conceder equipos que están dentro de tu propio alcance.")
    elif scope_type == "case":
        if db.execute("SELECT 1 FROM cases WHERE id = ?", (scope_id,)).fetchone() is None:
            raise PolicyError("El caso no existe.")
        if int(scope_id) not in actor_scope:
            raise PolicyError("Solo puedes conceder casos que están dentro de tu propio alcance.")
    else:
        raise PolicyError("Tipo de alcance no válido.")
    return target


def check_document_acl(db: sqlite3.Connection, actor, document_id: int, target_id: Optional[int]):
    if not has_permission(db, actor, "permissions.manage"):
        raise PolicyError("No tienes permiso para administrar permisos.")
    document = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if document is None:
        raise PolicyError("El documento no existe.")
    if int(document["case_id"]) not in case_scope(db, actor):
        raise PolicyError("Solo puedes restringir documentos de casos dentro de tu alcance.")
    if target_id is not None:
        check_can_manage_user(db, actor, target_id)
    return document


def describe(db: sqlite3.Connection, user) -> Mapping[str, object]:
    """Resumen verificable de la política efectiva de un usuario (para la vista de permisos)."""
    return {
        "permissions": sorted(effective_permissions(db, user)),
        "overrides": permission_overrides(db, _uid(user)),
        "scope": {cid: sorted(v) for cid, v in case_scope(db, user).items()},
        "assistant_scope": {cid: sorted(v) for cid, v in assistant_scope(db, user).items()},
    }
