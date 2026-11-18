"""Administración: usuarios, roles, equipos, expedientes y asignaciones."""
from __future__ import annotations

import io
from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, send_file, url_for

from vexa import runtime
from vexa.database import connect
from vexa.permissions import MANAGEMENT_PERMISSIONS, ROLES, can, permission_required, policy
from vexa.permissions.catalog import ROLES_ASSIGNABLE_BY
from vexa.routes.cases import upload_reply
from vexa.security import recovery
from vexa.services import audit, backups, exports
from vexa.services import cases as case_service
from vexa.services import messages as message_service
from vexa.services import notifications as notification_service
from vexa.services import users as user_service
from vexa.services.audit_view import local_time

bp = Blueprint("admin", __name__, url_prefix="/admin")


ADMIN_TABS = ("casos", "usuarios", "equipos", "supervision", "respaldos")


def _back(tab: str = "casos"):
    """Vuelve al panel en la pestaña donde se hizo la acción."""
    return redirect(url_for("admin.dashboard", tab=tab if tab in ADMIN_TABS else "casos"))


def _is_admin() -> bool:
    return g.user["role"] == "admin"


def _backup_info(settings) -> dict:
    """Estado de respaldos y de la clave de recuperación para la pestaña Respaldos (sin secretos)."""
    target = settings.backup_dir
    status = backups.read_status(settings.data_dir)
    status["last_ok_local"] = local_time(status.get("last_ok"))
    status["last_error_local"] = local_time(status.get("last_error_at"))
    same_drive = (target.resolve().drive or "/").lower() == (settings.data_dir.resolve().drive or "/").lower()
    return {
        "dir": str(target), "hours": settings.backup_hours, "keep": settings.backup_keep,
        "files": backups.list_backups(target), "status": status,
        "cloud": backups.looks_like_cloud(target), "same_drive": same_drive,
        "recovery": recovery.status(settings.data_dir),
    }


@bp.get("")
@permission_required(*MANAGEMENT_PERMISSIONS, any_of=True)
def dashboard():
    """El administrador ve toda la firma; el abogado jefe, solo sus abogados, sus equipos y su alcance."""
    settings = runtime().settings
    admin = _is_admin()
    with connect(settings.db_path) as db:
        assignees = policy.manageable_people(db, g.user)
        team_ids = None if admin else [t["id"] for t in db.execute("SELECT id FROM teams").fetchall()
                                       if policy.team_is_manageable(db, g.user, t["id"])]
        scope = None if admin else policy.case_scope(db, g.user)
    cases = []
    if can("cases.manage"):
        cases = case_service.all_cases(settings.db_path) if admin else case_service.cases_by_ids(settings.db_path, scope)
    all_users = user_service.list_users(settings.db_path) if admin else []
    users = []
    if can("users.manage"):
        users = all_users if admin else user_service.list_users(settings.db_path, supervised_by=g.user["id"])
    tabs = [t for t, allowed in (("casos", can("cases.manage")), ("usuarios", can("users.manage")),
                                 ("equipos", can("teams.manage")), ("supervision", admin and can("users.manage")),
                                 ("respaldos", admin))
            if allowed]
    requested = request.args.get("tab", "")
    return render_template(
        "admin.html",
        tabs=tabs, active_tab=requested if requested in tabs else (tabs[0] if tabs else ""),
        users=users,
        assignees=assignees,
        teams=user_service.list_teams(settings.db_path, team_ids),
        cases=cases,
        chiefs=[u for u in all_users if u["role"] == "chief_lawyer" and u["active"]],
        all_lawyers=[u for u in all_users if u["role"] == "lawyer" and u["active"]],
        supervision=user_service.supervision_map(settings.db_path) if admin else {},
        backup=_backup_info(settings) if admin else None,
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
        return _back("usuarios")
    try:
        user_id = user_service.create_user(runtime().settings.db_path, request.form.get("name", ""),
                                           request.form.get("username", ""), request.form.get("password", ""), role)
        if g.user["role"] == "chief_lawyer":
            # Un abogado creado por un jefe queda a su cargo (si no, no podría asignarle casos).
            user_service.add_supervision(runtime().settings.db_path, g.user["id"], user_id)
        audit.record("users.create", "ok", resource_type="user", resource_id=user_id, details={"rol": role})
        flash(f"Cuenta creada ({ROLES[role]}).", "success")
    except user_service.UserError as exc:
        flash(str(exc), "error")
    return _back("usuarios")


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
    return _back("usuarios")


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
    return _back("usuarios")


# -------------------------------------------------------------------- equipos
@bp.post("/teams")
@permission_required("teams.manage")
def create_team():
    settings = runtime().settings
    members = request.form.getlist("member_ids", type=int)
    try:
        with connect(settings.db_path) as db:
            policy.check_team_members(db, g.user, members)
        team_id = user_service.create_team(settings.db_path, request.form.get("name", ""), members)
        audit.record("teams.create", "ok", resource_type="team", resource_id=team_id)
        flash("Equipo creado.", "success")
    except policy.PolicyError as exc:
        audit.record("teams.create", "denied", reason=str(exc))
        flash(str(exc), "error")
    except user_service.UserError as exc:
        flash(str(exc), "error")
    return _back("equipos")


@bp.post("/teams/<int:team_id>/members")
@permission_required("teams.manage")
def update_team(team_id):
    settings = runtime().settings
    wanted = request.form.getlist("member_ids", type=int)
    try:
        with connect(settings.db_path) as db:
            policy.check_team_members(db, g.user, wanted, team_id=team_id)
        members = user_service.set_team_members(settings.db_path, team_id, wanted)
        audit.record("teams.members_change", "ok", resource_type="team", resource_id=team_id,
                     details={"integrantes": members})
        flash("Integrantes del equipo actualizados.", "success")
    except policy.PolicyError as exc:
        audit.record("teams.members_change", "denied", resource_type="team", resource_id=team_id, reason=str(exc))
        flash(str(exc), "error")
    except user_service.UserError as exc:
        flash(str(exc), "error")
    return _back("equipos")


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
        with connect(settings.db_path) as db:
            policy.check_assignee(db, g.user, assignment_type, assignee_id)
        if not uploads:
            raise case_service.CaseError("Adjunta al menos un documento admitido al caso.")
        files = []
        for uploaded in uploads:
            content = uploaded.read(settings.max_file_size + 1)
            files.append((case_service.validate_upload(uploaded.filename, content, settings.max_file_size), content))
        case_id = case_service.create_case(settings.db_path, settings.upload_dir, title=title, summary=summary,
                                           reference=reference, due_at=due_at, assignment_type=assignment_type,
                                           assignee_id=assignee_id, files=files, created_by=g.user["id"])
    except policy.PolicyError as exc:
        audit.record("cases.create", "denied", reason=str(exc))
        flash(str(exc), "error")
        return upload_reply(_back("casos"))
    except case_service.CaseError as exc:
        flash(str(exc), "error")
        return upload_reply(_back("casos"))
    notification_service.case_assigned(settings.db_path, case_id, g.user["id"])
    message_service.system(settings.db_path, case_id,
                           f"{g.user['name']} creó el caso y lo asignó a {message_service.assignee_label(settings.db_path, case_id)}.")
    audit.record("cases.create", "ok", resource_type="case", resource_id=case_id,
                 details={"asignacion": assignment_type, "responsable": assignee_id, "documentos": len(files)})
    (settings.watch_dir / str(case_id)).mkdir(parents=True, exist_ok=True)
    runtime().indexer.schedule(case_id)
    flash("Caso creado y asignado. Sus documentos se están preparando en segundo plano.", "success")
    return upload_reply(_back("casos"))


@bp.post("/cases/<int:case_id>/assignment")
@permission_required("cases.manage")
def reassign_case(case_id):
    settings = runtime().settings
    try:
        assignment_type, assignee_id = case_service.parse_assignment(request.form.get("assignment_type"),
                                                                     request.form.get("assignee_id", ""))
        with connect(settings.db_path) as db:
            policy.check_case_manageable(db, g.user, case_id)
            policy.check_assignee(db, g.user, assignment_type, assignee_id)
        case_service.reassign_case(settings.db_path, case_id, assignment_type, assignee_id)
        notification_service.case_assigned(settings.db_path, case_id, g.user["id"], reassigned=True)
        message_service.system(settings.db_path, case_id,
                               f"{g.user['name']} reasignó el caso a {message_service.assignee_label(settings.db_path, case_id)}.")
        audit.record("cases.assignment_change", "ok", resource_type="case", resource_id=case_id,
                     details={"asignacion": assignment_type, "responsable": assignee_id})
        flash("Asignación actualizada.", "success")
    except policy.PolicyError as exc:
        audit.record("cases.assignment_change", "denied", resource_type="case", resource_id=case_id, reason=str(exc))
        flash(str(exc), "error")
    except case_service.CaseError as exc:
        flash(str(exc), "error")
    return _back("casos")


@bp.post("/users/<int:chief_id>/lawyers")
@permission_required("users.manage")
def set_supervised_lawyers(chief_id):
    """Solo el administrador decide qué abogados quedan a cargo de cada abogado jefe."""
    settings = runtime().settings
    try:
        with connect(settings.db_path) as db:
            lawyer_ids = policy.check_supervision(db, g.user, chief_id, request.form.getlist("lawyer_ids", type=int))
        user_service.set_supervised_lawyers(settings.db_path, chief_id, lawyer_ids)
        runtime().assistant.forget_user(chief_id)
        audit.record("users.supervision_change", "ok", resource_type="user", resource_id=chief_id,
                     details={"abogados": lawyer_ids})
        flash("Abogados a cargo actualizados.", "success")
    except policy.PolicyError as exc:
        audit.record("users.supervision_change", "denied", resource_type="user", resource_id=chief_id, reason=str(exc))
        flash(str(exc), "error")
    return _back("supervision")


@bp.post("/cases/<int:case_id>/due")
@permission_required("cases.set_deadline")
def set_due_date(case_id):
    """Solo el administrador (rol) cambia la fecha límite; se audita la fecha anterior y la nueva."""
    try:
        due_at = case_service.parse_due_date(request.form.get("due_at", "").strip())
        previous = case_service.set_due_date(runtime().settings.db_path, case_id, due_at)
        notification_service.due_date_changed(runtime().settings.db_path, case_id, g.user["id"], due_at)
        message_service.system(runtime().settings.db_path, case_id, message_service.due_change_text(
            g.user["name"], previous, due_at))
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
    return _back("usuarios")


# ------------------------------------------------------------- seguimiento
@bp.get("/seguimiento")
@permission_required("cases.manage")
def follow_up():
    data = _follow_up_data()
    return render_template("follow_up.html", data=data, status_labels=case_service.STATUS_LABELS)


def _follow_up_data() -> dict:
    """Seguimiento: toda la firma para el administrador; el alcance propio para el abogado jefe."""
    settings = runtime().settings
    case_ids = None
    if not _is_admin():
        with connect(settings.db_path) as db:
            case_ids = policy.case_scope(db, g.user)
    return case_service.follow_up(settings.db_path, case_ids=case_ids)


@bp.get("/seguimiento/exportar.xlsx")
@permission_required("cases.manage")
def follow_up_export():
    data = _follow_up_data()
    content = exports.follow_up_xlsx(data, case_service.DEADLINE_LABELS)
    audit.record("exports.follow_up", "ok", details={"casos": len(data["cases"])})
    name = f"vexa-seguimiento-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
    return send_file(io.BytesIO(content), as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.post("/respaldos")
@permission_required("users.manage")
def create_backup_now():
    """Respaldo manual inmediato (solo administrador). El servidor sigue funcionando mientras tanto."""
    if not _is_admin():
        audit.record("backups.create", "denied", reason="solo el administrador")
        flash("Solo el administrador puede crear respaldos.", "error")
        return _back("casos")
    try:
        path = backups.run_backup(runtime().settings, reason="manual")
        audit.record("backups.create", "ok", details={"archivo": path.name})
        flash(f"Respaldo creado: {path.name}", "success")
    except Exception as exc:
        audit.record("backups.create", "error", reason=str(exc)[:200])
        flash(f"No se pudo crear el respaldo: {exc}", "error")
    return _back("respaldos")
