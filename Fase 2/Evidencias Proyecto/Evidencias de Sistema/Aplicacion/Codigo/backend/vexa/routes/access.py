"""Gestión de permisos: overrides por usuario, alcances (firma/equipo/caso) y restricciones documentales."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from vexa import runtime
from vexa.database import connect
from vexa.permissions import permission_required, policy
from vexa.permissions.catalog import SCOPE_TYPES
from vexa.services import access_view, audit
from vexa.services import cases as case_service
from vexa.services import users as user_service

bp = Blueprint("access", __name__, url_prefix="/admin/permissions")


def _back(user_id=None, case_id=None):
    """Vuelve a la pestaña correspondiente: por persona (user_id) o por documento (case_id)."""
    mode = "documentos" if case_id else "personas"
    return redirect(url_for("access.page", mode=mode, user_id=user_id or None, case_id=case_id or None))


@bp.get("")
@permission_required("permissions.manage")
def page():
    settings = runtime().settings
    mode = "documentos" if request.args.get("mode") == "documentos" else "personas"
    user_id = request.args.get("user_id", type=int)
    case_id = request.args.get("case_id", type=int)
    admin = g.user["role"] == "admin"
    selected = summary = None
    groups, grants, documents = [], [], []
    with connect(settings.db_path) as db:
        people = access_view.manageable_people(db, g.user)
        visible_ids = {p["id"] for p in people}
        scope = policy.case_scope(db, g.user)
        if user_id and user_id in visible_ids:
            selected = db.execute("SELECT id, name, username, role, active FROM users WHERE id = ?",
                                  (user_id,)).fetchone()
            summary = policy.describe(db, selected)
            groups = access_view.permission_groups(db, selected)
            grants = db.execute("""SELECT g.*, t.name AS team_name, c.title AS case_title
                                   FROM access_grants g LEFT JOIN teams t ON g.scope_type='team' AND t.id=g.scope_id
                                   LEFT JOIN cases c ON g.scope_type='case' AND c.id=g.scope_id
                                   WHERE g.user_id = ? ORDER BY g.scope_type, g.id""", (user_id,)).fetchall()
        if case_id and case_id in scope:
            me = db.execute("SELECT id, name, username, role, active FROM users WHERE id = ?", (g.user["id"],)).fetchone()
            listed = people if admin else [*people, me]
            documents = access_view.document_cards(db, g.user, case_id, listed)
        team_ids = None if admin else [t["id"] for t in db.execute("SELECT id FROM teams").fetchall()
                                       if policy.team_is_manageable(db, g.user, t["id"])]
        firm = policy.has_firm_scope(db, g.user)
    # El jefe solo ve casos de su alcance: los títulos de otros casos no aparecen en esta página.
    cases = case_service.all_cases(settings.db_path) if admin else case_service.cases_by_ids(settings.db_path, scope)
    return render_template(
        "permissions.html", mode=mode, people=people, selected=selected, summary=summary, groups=groups,
        grants=grants, scope_types=SCOPE_TYPES, can_grant_firm=firm,
        teams=user_service.list_teams(settings.db_path, team_ids), cases=cases, case_id=case_id,
        current_case=next((c for c in cases if c["id"] == case_id), None), documents=documents,
        acl_people=[p for p in people if p["id"] != g.user["id"] and p["active"]],
    )


@bp.post("/users/<int:user_id>/override")
@permission_required("permissions.manage")
def set_override(user_id):
    permission = request.form.get("permission", "")
    effect = request.form.get("effect", "")
    db_path = runtime().settings.db_path
    try:
        with connect(db_path) as db:
            policy.check_permission_override(db, g.user, user_id, permission, effect)
            if effect == "clear":
                db.execute("DELETE FROM user_permissions WHERE user_id = ? AND permission = ?", (user_id, permission))
            else:
                db.execute("INSERT INTO user_permissions(user_id, permission, effect, granted_by) VALUES (?, ?, ?, ?) "
                           "ON CONFLICT(user_id, permission) DO UPDATE SET effect = excluded.effect, "
                           "granted_by = excluded.granted_by, created_at = CURRENT_TIMESTAMP",
                           (user_id, permission, effect, g.user["id"]))
        runtime().assistant.forget_user(user_id)
        audit.record("permissions.override", "ok", resource_type="user", resource_id=user_id,
                     details={"permiso": permission, "efecto": effect})
        flash("Permiso actualizado.", "success")
    except policy.PolicyError as exc:
        audit.record("permissions.override", "denied", resource_type="user", resource_id=user_id, reason=str(exc),
                     details={"permiso": permission, "efecto": effect})
        flash(str(exc), "error")
    return _back(user_id)


@bp.post("/users/<int:user_id>/grants")
@permission_required("permissions.manage")
def add_grant(user_id):
    scope_type = request.form.get("scope_type", "")
    scope_id = None
    db_path = runtime().settings.db_path
    try:
        if scope_type != "firm":
            kind, _, raw_id = request.form.get("scope_id", "").partition(":")
            if kind != scope_type or not raw_id.isdigit():
                raise policy.PolicyError("Selecciona un equipo o un caso que coincida con el tipo de alcance.")
            scope_id = int(raw_id)
        with connect(db_path) as db:
            policy.check_scope_grant(db, g.user, user_id, scope_type, scope_id)
            db.execute("INSERT OR IGNORE INTO access_grants(user_id, scope_type, scope_id, granted_by) VALUES (?, ?, ?, ?)",
                       (user_id, scope_type, scope_id, g.user["id"]))
        audit.record("permissions.grant", "ok", resource_type="user", resource_id=user_id,
                     details={"alcance": scope_type, "id": scope_id})
        flash("Alcance concedido.", "success")
    except policy.PolicyError as exc:
        audit.record("permissions.grant", "denied", resource_type="user", resource_id=user_id, reason=str(exc),
                     details={"alcance": scope_type, "id": scope_id})
        flash(str(exc), "error")
    return _back(user_id)


@bp.post("/grants/<int:grant_id>/revoke")
@permission_required("permissions.manage")
def revoke_grant(grant_id):
    db_path = runtime().settings.db_path
    user_id = None
    try:
        with connect(db_path) as db:
            grant = db.execute("SELECT * FROM access_grants WHERE id = ?", (grant_id,)).fetchone()
            if grant is None:
                raise policy.PolicyError("La concesión no existe.")
            user_id = grant["user_id"]
            policy.check_can_manage_user(db, g.user, user_id)
            db.execute("DELETE FROM access_grants WHERE id = ?", (grant_id,))
        runtime().assistant.forget_user(user_id)
        audit.record("permissions.revoke", "ok", resource_type="user", resource_id=user_id,
                     details={"alcance": grant["scope_type"], "id": grant["scope_id"]})
        flash("Alcance revocado.", "success")
    except policy.PolicyError as exc:
        audit.record("permissions.revoke", "denied", resource_type="grant", resource_id=grant_id, reason=str(exc))
        flash(str(exc), "error")
    return _back(user_id)


@bp.post("/documents/<int:document_id>/restriction")
@permission_required("permissions.manage")
def set_restriction(document_id):
    restricted = request.form.get("restricted") == "1"
    db_path = runtime().settings.db_path
    case_id = None
    try:
        with connect(db_path) as db:
            document = policy.check_document_acl(db, g.user, document_id, None)
            case_id = document["case_id"]
            db.execute("UPDATE documents SET restricted = ? WHERE id = ?", (1 if restricted else 0, document_id))
        runtime().indexer.invalidate_case(case_id)
        audit.record("documents.restriction", "ok", resource_type="document", resource_id=document_id,
                     details={"restringido": restricted})
        flash("Restricción del documento actualizada.", "success")
    except policy.PolicyError as exc:
        audit.record("documents.restriction", "denied", resource_type="document", resource_id=document_id,
                     reason=str(exc))
        flash(str(exc), "error")
    return _back(case_id=case_id)


@bp.post("/documents/<int:document_id>/acl")
@permission_required("permissions.manage")
def set_document_acl(document_id):
    target_id = request.form.get("user_id", type=int)
    effect = request.form.get("effect", "")
    db_path = runtime().settings.db_path
    case_id = None
    try:
        if effect not in {"allow", "deny", "clear"} or not target_id:
            raise policy.PolicyError("Selecciona un usuario y un efecto válido.")
        with connect(db_path) as db:
            document = policy.check_document_acl(db, g.user, document_id, target_id)
            case_id = document["case_id"]
            if effect == "clear":
                db.execute("DELETE FROM document_acl WHERE document_id = ? AND user_id = ?", (document_id, target_id))
            else:
                db.execute("INSERT INTO document_acl(document_id, user_id, effect, granted_by) VALUES (?, ?, ?, ?) "
                           "ON CONFLICT(document_id, user_id) DO UPDATE SET effect = excluded.effect, "
                           "granted_by = excluded.granted_by, created_at = CURRENT_TIMESTAMP",
                           (document_id, target_id, effect, g.user["id"]))
        runtime().assistant.forget_user(target_id)
        audit.record("documents.acl", "ok", resource_type="document", resource_id=document_id,
                     details={"usuario": target_id, "efecto": effect})
        flash("Regla del documento actualizada.", "success")
    except policy.PolicyError as exc:
        audit.record("documents.acl", "denied", resource_type="document", resource_id=document_id, reason=str(exc))
        flash(str(exc), "error")
    return _back(case_id=case_id)
