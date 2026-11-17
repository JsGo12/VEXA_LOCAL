"""Autorización centralizada para las rutas Flask. Todas las comprobaciones ocurren en el backend."""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import abort, current_app, g, redirect, url_for

from vexa.database import connect
from vexa.permissions import policy
from vexa.permissions.catalog import MANAGEMENT_PERMISSIONS, PERMISSIONS, ROLES  # noqa: F401
from vexa.services import audit


def db():
    return connect(current_app.config["VEXA_DB_PATH"])


def current_permissions() -> set:
    if g.get("user") is None:
        return set()
    cached = g.get("_vexa_permissions")
    if cached is None:
        with db() as conn:
            cached = policy.effective_permissions(conn, g.user)
        g._vexa_permissions = cached
    return cached


def can(permission: str) -> bool:
    return permission in current_permissions()


def deny(action: str, reason: str, resource_type=None, resource_id=None):
    audit.record("access.denied", "denied", resource_type=resource_type, resource_id=resource_id,
                 reason=reason, details={"intento": action})
    abort(403)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def permission_required(*permissions: str, any_of: bool = False):
    """Exige todos los permisos indicados (o al menos uno si any_of=True)."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            have = current_permissions()
            ok = any(p in have for p in permissions) if any_of else all(p in have for p in permissions)
            if not ok:
                deny(view.__name__, "falta permiso: " + ",".join(permissions))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def require_case(case_id: int, permission: str = "cases.view"):
    """Devuelve el caso con su asignación, o 404/403 (auditado)."""
    with db() as conn:
        case = conn.execute("""
            SELECT c.*, a.user_id AS assigned_user_id, a.team_id,
                   u.name AS assignee_name, t.name AS team_name
            FROM cases c
            JOIN case_assignments a ON a.case_id = c.id
            LEFT JOIN users u ON u.id = a.user_id
            LEFT JOIN teams t ON t.id = a.team_id
            WHERE c.id = ?
        """, (case_id,)).fetchone()
        if case is None:
            abort(404)
        if not policy.has_permission(conn, g.user, permission):
            deny(permission, "falta permiso: " + permission, "case", case_id)
        if not policy.case_paths(conn, g.user, case_id):
            deny(permission, "expediente fuera de su alcance", "case", case_id)
    return case


def require_document(document_id: int, permission: str = "documents.download"):
    with db() as conn:
        document = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if document is None:
            abort(404)
        if not policy.document_allowed(conn, g.user, document, permission):
            deny(permission, "documento fuera de su alcance o restringido", "document", document_id)
    return document


def visible_documents(case_id: int):
    with db() as conn:
        return policy.visible_documents(conn, g.user, case_id)


def install(app) -> None:
    @app.context_processor
    def _inject_permissions():
        return {"can": can, "ROLE_LABELS": ROLES}
