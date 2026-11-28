"""Protecciones HTTP comunes: CSRF por sesión, cabeceras de seguridad y carga del usuario."""
from __future__ import annotations

import secrets
import time

from flask import Flask, abort, flash, g, jsonify, redirect, request, session, url_for

from vexa.database import connect

# Peticiones automáticas de la página (campana, mensajes nuevos, estado de indexación…): no cuentan como uso
# para el cierre por inactividad. El JavaScript las marca con esta cabecera.
BACKGROUND_HEADER = "X-Vexa-Background"
IDLE_MESSAGE = "Tu sesión se cerró por inactividad. Vuelve a iniciar sesión."

# Rutas disponibles mientras la cuenta tiene un cambio de contraseña pendiente.
PASSWORD_GATE_ALLOWED = {"auth.change_password", "auth.logout", "static", "system.health"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def _check_idle(limit: int):
    """Cierra la sesión si pasó `limit` segundos sin uso. Devuelve la respuesta a enviar, o None."""
    now = int(time.time())
    last = session.get("last_seen")
    if limit and last is not None and now - int(last) > limit:
        from vexa.services import audit
        audit.record("auth.session_expired", "ok", details={"minutos": limit // 60})
        g.user = None
        session.clear()
        csrf_token()
        if request.path.startswith("/api/") or request.headers.get(BACKGROUND_HEADER):
            return jsonify(ok=False, expired=True, error=IDLE_MESSAGE), 401
        flash(IDLE_MESSAGE, "error")
        return redirect(url_for("auth.login"))
    if not request.headers.get(BACKGROUND_HEADER) or last is None:
        session["last_seen"] = now
    return None


def install(app: Flask) -> None:
    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": csrf_token}

    @app.before_request
    def _prepare_request():
        csrf_token()
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
                abort(400, "Token de formulario inválido. Actualiza la página e inténtalo nuevamente.")
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            with connect(app.config["VEXA_DB_PATH"]) as db:
                g.user = db.execute(
                    "SELECT id, name, username, role, must_change_password, session_epoch "
                    "FROM users WHERE id = ? AND active = 1", (user_id,)
                ).fetchone()
            # Cambio de contraseña, desactivación o cambio de rol invalidan las sesiones anteriores.
            if g.user is None or g.user["session_epoch"] != session.get("epoch", 0):
                g.user = None
                session.clear()
                csrf_token()
        if g.user is not None and request.endpoint != "static":
            expired = _check_idle(app.config.get("VEXA_IDLE_SECONDS", 0))
            if expired is not None:
                return expired
        if g.user is not None and g.user["must_change_password"] and request.endpoint not in PASSWORD_GATE_ALLOWED:
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Debes cambiar tu contraseña antes de continuar."), 403
            return redirect(url_for("auth.change_password"))

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if g.get("user") is not None:
            response.headers.setdefault("Cache-Control", "no-store")
        return response
