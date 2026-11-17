"""Consulta del registro de auditoría (por páginas)."""
from __future__ import annotations

import io
import math
from datetime import datetime

from flask import Blueprint, g, render_template, request, send_file, url_for

from vexa import runtime
from vexa.database import connect
from vexa.permissions import permission_required, policy
from vexa.services import audit, audit_view, exports
from vexa.services import users as user_service

bp = Blueprint("audit", __name__, url_prefix="/admin/audit")
PER_PAGE = 50


def _page_numbers(current: int, last: int) -> list:
    """Números a mostrar: 1 … 4 5 [6] 7 8 … 20 (None = separador)."""
    wanted = {1, last, *range(current - 2, current + 3)}
    pages, previous = [], 0
    for number in sorted(n for n in wanted if 1 <= n <= last):
        if number - previous > 1:
            pages.append(None)
        pages.append(number)
        previous = number
    return pages


@bp.get("")
@permission_required("audit.view")
def page():
    settings = runtime().settings
    audit.purge_older_than(settings.db_path, settings.audit_retention_days)
    filters = {
        "action": request.args.get("action") or None,
        "user_id": request.args.get("user_id", type=int),
        "result": request.args.get("result") if request.args.get("result") in {"ok", "denied", "error"} else None,
    }
    current = max(1, request.args.get("page", 1, type=int) or 1)
    rows, total, actions = audit.query(settings.db_path, page=current, per_page=PER_PAGE, **filters)
    last = max(1, math.ceil(total / PER_PAGE))
    if current > last:                                     # p. ej. tras borrar eventos antiguos
        current = last
        rows, total, actions = audit.query(settings.db_path, page=current, per_page=PER_PAGE, **filters)
    # Títulos de casos y documentos solo para lo que está en el alcance de quien consulta.
    with connect(settings.db_path) as db:
        visible = None if policy.has_firm_scope(db, g.user) else set(policy.case_scope(db, g.user))
    kept = {k: v for k, v in filters.items() if v}

    def page_url(number: int) -> str:
        return url_for("audit.page", page=number, **kept)

    action_options = sorted(((a, audit_view.action_label(a)) for a in actions), key=lambda item: item[1])
    return render_template(
        "audit.html", rows=audit_view.present(settings.db_path, rows, visible), actions=action_options,
        filters=filters, users=user_service.list_users(settings.db_path),
        pagination={"current": current, "last": last, "total": total, "pages": _page_numbers(current, last),
                    "first_item": (current - 1) * PER_PAGE + 1 if total else 0,
                    "last_item": min(current * PER_PAGE, total)},
        page_url=page_url, retention_days=settings.audit_retention_days)


EXPORT_LIMIT = 5000


@bp.get("/exportar.xlsx")
@permission_required("audit.view")
def export():
    """Exporta los eventos que cumplen los filtros actuales (máximo 5000), en lenguaje claro."""
    settings = runtime().settings
    filters = {
        "action": request.args.get("action") or None,
        "user_id": request.args.get("user_id", type=int),
        "result": request.args.get("result") if request.args.get("result") in {"ok", "denied", "error"} else None,
    }
    rows, total, _ = audit.query(settings.db_path, page=1, per_page=EXPORT_LIMIT, **filters)
    with connect(settings.db_path) as db:
        visible = None if policy.has_firm_scope(db, g.user) else set(policy.case_scope(db, g.user))
    content = exports.audit_xlsx(audit_view.present(settings.db_path, rows, visible))
    audit.record("exports.audit", "ok", details={"eventos": len(rows)})
    name = f"vexa-auditoria-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
    return send_file(io.BytesIO(content), as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
