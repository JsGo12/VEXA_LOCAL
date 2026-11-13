"""Administración: usuarios, roles, equipos, expedientes y asignaciones."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from vexa import runtime
from vexa.database import connect
from vexa.permissions import MANAGEMENT_PERMISSIONS, ROLES, can, permission_required, policy
from vexa.permissions.catalog import ROLES_ASSIGNABLE_BY
from vexa.services import audit
from vexa.services import cases as case_service
from vexa.services import users as user_service

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _back():
    return redirect(url_for("admin.dashboard"))


@bp.get("")
@permission_required(*MANAGEMENT_PERMISSIONS, any_of=True)
def dashboard():
    settings = runtime().settings
    return render_template(
        "admin.html",
        users=user_service.list_users(settings.db_path) if can("users.manage") else [],
        assignees=user_service.assignable_users(settings.db_path),
        teams=user_service.list_teams(settings.db_path),
        cases=case_service.all_cases(settings.db_path) if can("cases.manage") else [],
        assignable_roles=sorted(ROLES_ASSIGNABLE_BY.get(g.user["role"], frozenset())),
        max_mb=settings.max_file_size // (1024 * 1024),
    )


# ------------------------------------------------------------------- usuarios
@bp.post("/users")
@permission_required("users.manage")
def create_user():
    role = request.form.get("role", "lawyer")
    if role not in ROLES_ASSIGNABLE_BY.get(g.user["role"], frozenset()):
        audit.record("users.create", "denied", reason="rol no asignable", details={"rol": role})
        flash("No puedes crear cuentas con ese rol.", "error")
        return _back()
    try:
        user_id = user_service.create_user(runtime().settings.db_path, request.form.get("name", ""),
                                           request.form.get("username", ""), request.form.get("password", ""), role)
        audit.record("users.create", "ok", resource_type="user", resource_id=user_id, details={"rol": role})
        flash(f"Cuenta creada ({ROLES[role]}).", "success")
    except user_service.UserError as exc:
        flash(str(exc), "error")
    return _back()


@bp.post("/users/<int:user_id>/role")
@permission_required("users.manage")
def change_role(user_id):
    new_role = request.form.get("role", "")
    settings = runtime().settings
    try:
        with connect(settings.db_path) as db:
            target = policy.check_role_change(db, g.user, user_id, new_role)
        user_service.set_role(settings.db_path, user_id, new_role)
        runtime().assistant.forget_user(user_id)
        audit.record("users.role_change", "ok", resource_type="user", resource_id=user_id,
                     details={"antes": target["role"], "despues": new_role})
        flash("Rol actualizado.", "success")
    except policy.PolicyError as exc:
        audit.record("users.role_change", "denied", resource_type="user", resource_id=user_id, reason=str(exc))
        flash(str(exc), "error")
    return _back()


@bp.post("/users/<int:user_id>/active")
@permission_required("users.manage")
def change_active(user_id):
    active = request.form.get("active") == "1"
    settings = runtime().settings
    try:
        with connect(settings.db_path) as db:
            policy.check_can_manage_user(db, g.user, user_id)
        user_service.set_active(settings.db_path, user_id, active)
        runtime().assistant.forget_user(user_id)
        audit.record("users.activate" if active else "users.deactivate", "ok", resource_type="user",
                     resource_id=user_id)
        flash("Cuenta activada." if active else "Cuenta desactivada.", "success")
    except policy.PolicyError as exc:
        audit.record("users.active_change", "denied", resource_type="user", resource_id=user_id, reason=str(exc))
        flash(str(exc), "error")
    return _back()


# -------------------------------------------------------------------- equipos
@bp.post("/teams")
@permission_required("teams.manage")
def create_team():
    try:
        team_id = user_service.create_team(runtime().settings.db_path, request.form.get("name", ""),
                                           request.form.getlist("member_ids", type=int))
        audit.record("teams.create", "ok", resource_type="team", resource_id=team_id)
        flash("Equipo creado.", "success")
    except user_service.UserError as exc:
        flash(str(exc), "error")
    return _back()


@bp.post("/teams/<int:team_id>/members")
@permission_required("teams.manage")
def update_team(team_id):
    try:
        members = user_service.set_team_members(runtime().settings.db_path, team_id,
                                                request.form.getlist("member_ids", type=int))
        audit.record("teams.members_change", "ok", resource_type="team", resource_id=team_id,
                     details={"integrantes": members})
        flash("Integrantes del equipo actualizados.", "success")
    except user_service.UserError as exc:
        flash(str(exc), "error")
    return _back()


# ------------------------------------------------------------------- expedientes
@bp.post("/cases")
@permission_required("cases.manage")
def create_case():
    settings = runtime().settings
    title = request.form.get("title", "").strip()[:160]
    summary = request.form.get("summary", "").strip()[:800]
    reference = request.form.get("reference", "").strip()[:60]
    uploads = [item for item in request.files.getlist("documents") if item and item.filename]
    try:
        if not title or not summary:
            raise case_service.CaseError("Completa el caso, resumen, responsable y fecha límite.")
        assignment_type, assignee_id = case_service.parse_assignment(request.form.get("assignment_type"),
                                                                     request.form.get("assignee_id", ""))
        due_at = case_service.parse_due_date(request.form.get("due_at", "").strip())
        if not uploads:
            raise case_service.CaseError("Adjunta al menos un documento admitido al caso.")
        files = []
        for uploaded in uploads:
            content = uploaded.read(settings.max_file_size + 1)
            files.append((case_service.validate_upload(uploaded.filename, content, settings.max_file_size), content))
        case_id = case_service.create_case(settings.db_path, settings.upload_dir, title=title, summary=summary,
                                           reference=reference, due_at=due_at, assignment_type=assignment_type,
                                           assignee_id=assignee_id, files=files, created_by=g.user["id"])
    except case_service.CaseError as exc:
        flash(str(exc), "error")
        return _back()
    audit.record("cases.create", "ok", resource_type="case", resource_id=case_id,
                 details={"asignacion": assignment_type, "responsable": assignee_id, "documentos": len(files)})
    (settings.watch_dir / str(case_id)).mkdir(parents=True, exist_ok=True)
    runtime().indexer.schedule(case_id)
    flash("Caso creado y asignado. Sus documentos se están preparando en segundo plano.", "success")
    return _back()


@bp.post("/cases/<int:case_id>/assignment")
@permission_required("cases.manage")
def reassign_case(case_id):
    try:
        assignment_type, assignee_id = case_service.parse_assignment(request.form.get("assignment_type"),
                                                                     request.form.get("assignee_id", ""))
        case_service.reassign_case(runtime().settings.db_path, case_id, assignment_type, assignee_id)
        audit.record("cases.assignment_change", "ok", resource_type="case", resource_id=case_id,
                     details={"asignacion": assignment_type, "responsable": assignee_id})
        flash("Asignación actualizada.", "success")
    except case_service.CaseError as exc:
        flash(str(exc), "error")
    return _back()


@bp.post("/cases/<int:case_id>/due")
@permission_required("cases.set_deadline")
def set_due_date(case_id):
    """Solo el administrador (rol) cambia la fecha límite; se audita la fecha anterior y la nueva."""
    try:
        due_at = case_service.parse_due_date(request.form.get("due_at", "").strip())
        previous = case_service.set_due_date(runtime().settings.db_path, case_id, due_at)
        audit.record("cases.due_date_change", "ok", resource_type="case", resource_id=case_id,
                     details={"anterior": previous, "nueva": due_at})
        flash("Fecha límite actualizada.", "success")
    except case_service.CaseError as exc:
        audit.record("cases.due_date_change", "denied", resource_type="case", resource_id=case_id, reason=str(exc))
        flash(str(exc), "error")
    return redirect(url_for("admin.follow_up"))


@bp.post("/users/<int:user_id>/password")
@permission_required("users.manage")
def reset_password(user_id):
    settings = runtime().settings
    try:
        with connect(settings.db_path) as db:
            policy.check_can_manage_user(db, g.user, user_id)
        user_service.reset_password(settings.db_path, user_id, request.form.get("password", ""))
        audit.record("users.password_reset", "ok", resource_type="user", resource_id=user_id)
        flash("Contraseña temporal asignada. La persona deberá cambiarla al entrar.", "success")
    except (policy.PolicyError, user_service.UserError) as exc:
        audit.record("users.password_reset", "denied", resource_type="user", resource_id=user_id, reason=str(exc))
        flash(str(exc), "error")
    return _back()


# ------------------------------------------------------------- seguimiento
@bp.get("/seguimiento")
@permission_required("cases.manage")
def follow_up():
    data = case_service.follow_up(runtime().settings.db_path)
    return render_template("follow_up.html", data=data, status_labels=case_service.STATUS_LABELS)
