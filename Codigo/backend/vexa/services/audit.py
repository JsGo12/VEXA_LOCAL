"""Registro de auditoría. Nunca guarda contraseñas, tokens, preguntas ni contenido documental."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Mapping, Optional

from flask import current_app, g, has_request_context, request

from vexa.database import connect

LOGGER = logging.getLogger(__name__)
PURGE_EVERY_SECONDS = 6 * 60 * 60
_last_purge = {"t": 0.0}
_purge_lock = threading.Lock()
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
        _maybe_purge(path)
    except Exception:
        LOGGER.exception("No se pudo escribir el evento de auditoría %s", action)


def _maybe_purge(db_path) -> None:
    """Aplica la retención como mucho cada 6 horas mientras el servidor sigue encendido."""
    days = current_app.config.get("VEXA_AUDIT_RETENTION_DAYS", 0) if has_request_context() else 0
    if not days:
        return
    with _purge_lock:
        if time.monotonic() - _last_purge["t"] < PURGE_EVERY_SECONDS:
            return
        _last_purge["t"] = time.monotonic()
    purge_older_than(db_path, days)


def purge_older_than(db_path, days: int) -> int:
    """Borra los eventos con más de `days` días (0 = conservar todo). Devuelve cuántos se borraron.

    created_at se guarda como texto ISO en UTC ('2026-11-14T01:15:51.123Z'), así que comparar como
    texto contra la misma forma de fecha es correcto.
    """
    if not days or days <= 0:
        return 0
    with connect(db_path) as db:
        removed = db.execute(
            "DELETE FROM audit_log WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)",
            (f"-{int(days)} days",)).rowcount
    if removed:
        LOGGER.info("Auditoría: %s evento(s) con más de %s días eliminados.", removed, days)
    return removed


def query(db_path, *, page: int = 1, per_page: int = 50, action: Optional[str] = None,
          user_id: Optional[int] = None, result: Optional[str] = None):
    """Una página de eventos (más recientes primero). Devuelve (filas, total, acciones distintas)."""
    clauses, params = [], []
    if action:
        clauses.append("action = ?"); params.append(action)
    if user_id:
        clauses.append("user_id = ?"); params.append(user_id)
    if result:
        clauses.append("result = ?"); params.append(result)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    per_page = max(1, min(int(per_page), 5000))
    page = max(1, int(page))
    with connect(db_path) as db:
        total = db.execute(f"SELECT COUNT(*) FROM audit_log {where}", params).fetchone()[0]
        rows = db.execute(f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                          (*params, per_page, (page - 1) * per_page)).fetchall()
        actions = [r[0] for r in db.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]
    return rows, total, actions
