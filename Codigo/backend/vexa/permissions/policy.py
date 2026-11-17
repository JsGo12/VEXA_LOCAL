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
    supervised  caso asignado a un abogado a cargo del usuario (chief_lawyers), directamente o
                a un equipo del que ese abogado es integrante. Lo concede el administrador al
                asignarle abogados a un abogado jefe.
El rol nunca concede alcance de datos por sí mismo.

Abogado jefe (no administrador): solo administra a los abogados que el administrador le asignó
(cuentas, permisos, equipos formados solo por ellos y asignación de casos a ellos o a esos equipos).

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
    "supervised": "assistant.team_access",
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
    add(db.execute("""SELECT a.case_id FROM case_assignments a
                      JOIN chief_lawyers s ON s.lawyer_id = a.user_id WHERE s.chief_id = ?""", (uid,)), "supervised")
    add(db.execute("""SELECT DISTINCT a.case_id FROM case_assignments a
                      JOIN team_members m ON m.team_id = a.team_id
                      JOIN chief_lawyers s ON s.lawyer_id = m.user_id WHERE s.chief_id = ?""", (uid,)), "supervised")
    return scope


# ------------------------------------------------------------ abogados a cargo del jefe
def supervised_lawyer_ids(db: sqlite3.Connection, chief_id: int) -> Set[int]:
    """Abogados activos que el administrador asignó a este abogado jefe."""
    return {int(r[0]) for r in db.execute(
        """SELECT s.lawyer_id FROM chief_lawyers s JOIN users u ON u.id = s.lawyer_id
           WHERE s.chief_id = ? AND u.active = 1 AND u.role = 'lawyer'""", (chief_id,))}


def manageable_people(db: sqlite3.Connection, actor) -> List[sqlite3.Row]:
    """Personas a las que el actor puede asignar casos o incluir en equipos."""
    if actor["role"] == "admin":
        return db.execute("SELECT id, name, username, role FROM users WHERE active = 1 AND role IN "
                          "('lawyer', 'chief_lawyer') ORDER BY name").fetchall()
    return db.execute("""SELECT u.id, u.name, u.username, u.role FROM users u
                         JOIN chief_lawyers s ON s.lawyer_id = u.id
                         WHERE s.chief_id = ? AND u.active = 1 AND u.role = 'lawyer' ORDER BY u.name""",
                      (_uid(actor),)).fetchall()


def _team_member_ids(db: sqlite3.Connection, team_id: int) -> Set[int]:
    return {int(r[0]) for r in db.execute("SELECT user_id FROM team_members WHERE team_id = ?", (team_id,))}


def team_is_manageable(db: sqlite3.Connection, actor, team_id: int) -> bool:
    """El administrador maneja todos; el jefe, solo equipos formados únicamente por sus abogados."""
    if actor["role"] == "admin":
        return True
    members = _team_member_ids(db, team_id)
    return bool(members) and members <= supervised_lawyer_ids(db, _uid(actor))


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
    """Nadie se administra a sí mismo; quien no es admin solo administra a los abogados a su cargo."""
    target = _target(db, target_id)
    if int(target["id"]) == _uid(actor):
        raise PolicyError("No puedes modificar tus propios permisos, rol o estado.")
    if actor["role"] != "admin":
        if target["role"] != "lawyer":
            raise PolicyError("Solo un administrador puede modificar cuentas de administración o de abogado jefe.")
        if db.execute("SELECT 1 FROM chief_lawyers WHERE chief_id = ? AND lawyer_id = ?",
                      (_uid(actor), int(target["id"]))).fetchone() is None:
            raise PolicyError("Solo puedes administrar a los abogados que el administrador te asignó.")
    return target


def check_supervision(db: sqlite3.Connection, actor, chief_id: int, lawyer_ids: Iterable[int]) -> List[int]:
    """Solo el administrador asigna abogados a un abogado jefe. Devuelve los ids válidos."""
    if actor["role"] != "admin":
        raise PolicyError("Solo un administrador asigna abogados a un abogado jefe.")
    chief = _target(db, chief_id)
    if chief["role"] != "chief_lawyer":
        raise PolicyError("Solo se pueden asignar abogados a una cuenta de abogado jefe.")
    wanted = list(dict.fromkeys(int(i) for i in lawyer_ids))
    if not wanted:
        return []
    marks = ",".join("?" for _ in wanted)
    valid = [int(r[0]) for r in db.execute(
        f"SELECT id FROM users WHERE role = 'lawyer' AND id IN ({marks})", wanted)]
    if len(valid) != len(wanted):
        raise PolicyError("Solo se pueden asignar cuentas con rol de abogado/a.")
    return valid


def check_team_members(db: sqlite3.Connection, actor, member_ids: Iterable[int], team_id: Optional[int] = None) -> None:
    """El jefe solo arma equipos con sus abogados y solo edita equipos formados por ellos."""
    if actor["role"] == "admin":
        return
    if team_id is not None and not team_is_manageable(db, actor, team_id):
        raise PolicyError("Solo puedes modificar equipos formados por abogados a tu cargo.")
    allowed = supervised_lawyer_ids(db, _uid(actor))
    if not {int(m) for m in member_ids} <= allowed:
        raise PolicyError("Solo puedes incluir en equipos a los abogados que el administrador te asignó.")


def check_assignee(db: sqlite3.Connection, actor, assignment_type: str, assignee_id: int) -> None:
    """El jefe solo asigna casos a sus abogados o a equipos formados por ellos."""
    if actor["role"] == "admin":
        return
    if assignment_type == "user":
        if int(assignee_id) not in supervised_lawyer_ids(db, _uid(actor)):
            raise PolicyError("Solo puedes asignar casos a los abogados que el administrador te asignó.")
    elif not team_is_manageable(db, actor, int(assignee_id)):
        raise PolicyError("Solo puedes asignar casos a equipos formados por abogados a tu cargo.")


def check_case_manageable(db: sqlite3.Connection, actor, case_id: int) -> None:
    """El jefe solo reasigna casos dentro de su alcance."""
    if actor["role"] != "admin" and int(case_id) not in case_scope(db, actor):
        raise PolicyError("Solo puedes reasignar casos dentro de tu alcance.")


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
