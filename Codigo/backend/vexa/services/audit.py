"""Registro de auditoría. Nunca guarda contraseñas, tokens, preguntas ni contenido documental."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional

from flask import current_app, g, has_request_context, request

from vexa.database import connect

LOGGER = logging.getLogger(__name__)
_FORBIDDEN_KEYS = {"password", "contrasena", "contraseña", "token", "csrf_token", "question", "pregunta",
                   "content", "answer", "secret"}


def _clean(details: Optional[Mapping[str, Any]]) -> str:
    if not details:
        return ""
    safe = {k: v for k, v in details.items() if k.lower() not in _FORBIDDEN_KEYS}
    return json.dumps(safe, ensure_ascii=False, default=str)[:2000]


def record(action: str, result: str = "ok", *, resource_type: Optional[str] = None,
           resource_id: Any = None, reason: Optional[str] = None,
           details: Optional[Mapping[str, Any]] = None, user=None, username: Optional[str] = None,
           db_path=None) -> None:
    """Inserta un evento. Un fallo de auditoría se registra en el log pero no tumba la petición."""
    try:
        if user is None and has_request_context():
            user = g.get("user")
        ip = request.remote_addr if has_request_context() else None
        path = db_path or current_app.config["VEXA_DB_PATH"]
        with connect(path) as db:
            db.execute(
                "INSERT INTO audit_log(user_id, username, action, resource_type, resource_id, result, reason, ip, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user["id"] if user is not None else None,
                 (user["username"] if user is not None else username),
                 action, resource_type, None if resource_id is None else str(resource_id),
                 result, reason, ip, _clean(details)),
            )
    except Exception:
        LOGGER.exception("No se pudo escribir el evento de auditoría %s", action)


def query(db_path, *, limit: int = 200, action: Optional[str] = None, user_id: Optional[int] = None,
          result: Optional[str] = None):
    clauses, params = [], []
    if action:
        clauses.append("action = ?"); params.append(action)
    if user_id:
        clauses.append("user_id = ?"); params.append(user_id)
    if result:
        clauses.append("result = ?"); params.append(result)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as db:
        rows = db.execute(f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?",
                          (*params, max(1, min(int(limit), 1000)))).fetchall()
        actions = [r[0] for r in db.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]
    return rows, actions
