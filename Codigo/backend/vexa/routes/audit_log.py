"""Consulta del registro de auditoría."""
from __future__ import annotations

from flask import Blueprint, render_template, request

from vexa import runtime
from vexa.permissions import permission_required
from vexa.services import audit
from vexa.services import users as user_service

bp = Blueprint("audit", __name__, url_prefix="/admin/audit")


@bp.get("")
@permission_required("audit.view")
def page():
    settings = runtime().settings
    filters = {
        "action": request.args.get("action") or None,
        "user_id": request.args.get("user_id", type=int),
        "result": request.args.get("result") if request.args.get("result") in {"ok", "denied", "error"} else None,
    }
    rows, actions = audit.query(settings.db_path, limit=300, **filters)
    return render_template("audit.html", rows=rows, actions=actions, filters=filters,
                           users=user_service.list_users(settings.db_path))
