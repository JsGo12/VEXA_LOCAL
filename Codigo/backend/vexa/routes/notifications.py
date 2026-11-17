"""Notificaciones del usuario: página, abrir (marca como leída) y contador para la campana."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, redirect, render_template, url_for

from vexa import runtime
from vexa.database import connect
from vexa.permissions import login_required, policy
from vexa.services import notifications as notification_service
from vexa.services.audit_view import local_time

bp = Blueprint("notifications", __name__)


@bp.get("/notificaciones")
@login_required
def page():
    items = notification_service.list_for(runtime().settings.db_path, g.user["id"])
    for item in items:
        item["when"] = local_time(item["created_at"])
    return render_template("notifications.html", items=items)


@bp.get("/notificaciones/<int:notification_id>")
@login_required
def open_notification(notification_id):
    """Marca como leída y lleva al caso, solo si la persona todavía puede verlo."""
    db_path = runtime().settings.db_path
    item = notification_service.get_own(db_path, g.user["id"], notification_id)
    if item is None:
        return redirect(url_for("notifications.page"))
    notification_service.mark_read(db_path, g.user["id"], notification_id)
    if item["case_id"] is not None:
        with connect(db_path) as db:
            if policy.can_view_case(db, g.user, item["case_id"]):
                if item["kind"] == "mensaje":
                    return redirect(url_for("cases.case_workspace", case_id=item["case_id"], panel="mensajes")
                                    + "#mensajes")
                return redirect(url_for("cases.case_workspace", case_id=item["case_id"]))
    return redirect(url_for("notifications.page"))


@bp.post("/notificaciones/leer")
@login_required
def mark_all_read():
    notification_service.mark_read(runtime().settings.db_path, g.user["id"])
    return redirect(url_for("notifications.page"))


@bp.get("/api/notificaciones/contador")
@login_required
def unread_api():
    return jsonify(unread=notification_service.unread_count(runtime().settings.db_path, g.user["id"]))
