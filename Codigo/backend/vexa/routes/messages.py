"""Mensajes del equipo: bandeja general y conversación de cada caso."""
from __future__ import annotations

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from vexa import runtime
from vexa.permissions import login_required, permission_required, require_case
from vexa.services import audit
from vexa.services import messages as message_service
from vexa.services.audit_view import local_time

bp = Blueprint("messages", __name__)


def _wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "vexa-fetch"


def _serialize(items):
    return [{**m, "when": local_time(m["created_at"])} for m in items]


@bp.get("/mensajes")
@permission_required("cases.message")
def inbox():
    items = message_service.inbox(runtime().settings.db_path, g.user)
    for item in items:
        item["when"] = local_time(item["created_at"])
    return render_template("messages.html", items=items)


@bp.post("/case/<int:case_id>/mensajes")
@login_required
def send(case_id):
    require_case(case_id, "cases.message")
    db_path = runtime().settings.db_path
    try:
        message_id = message_service.post(db_path, case_id, g.user, request.form.get("body", ""))
        audit.record("messages.send", "ok", resource_type="case", resource_id=case_id)
    except message_service.MessageError as exc:
        if _wants_json():
            return jsonify(ok=False, error=str(exc)), 400
        flash(str(exc), "error")
        return redirect(url_for("cases.case_workspace", case_id=case_id) + "#mensajes")
    if _wants_json():
        after = request.form.get("after", type=int) or 0
        return jsonify(ok=True, id=message_id,
                       messages=_serialize(message_service.thread(db_path, case_id, g.user["id"], after_id=after)))
    return redirect(url_for("cases.case_workspace", case_id=case_id, panel="mensajes") + "#mensajes")


@bp.get("/api/case/<int:case_id>/mensajes")
@login_required
def fetch(case_id):
    """Mensajes nuevos (after=ID). Con read=1 marca la conversación como leída."""
    require_case(case_id, "cases.message")
    db_path = runtime().settings.db_path
    items = message_service.thread(db_path, case_id, g.user["id"], after_id=request.args.get("after", 0, type=int))
    if request.args.get("read") == "1":
        message_service.mark_read(db_path, case_id, g.user["id"])
    return jsonify(messages=_serialize(items),
                   unread=message_service.unread_count(db_path, case_id, g.user["id"]))
