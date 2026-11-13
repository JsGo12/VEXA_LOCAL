"""Inicio de sesión, cierre de sesión y redirección según el perfil."""
from __future__ import annotations

import secrets

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from vexa import runtime
from vexa.database import store
from vexa.permissions import MANAGEMENT_PERMISSIONS, can, login_required
from vexa.services import audit
from vexa.services import users as user_service

bp = Blueprint("auth", __name__)


def home_endpoint() -> str:
    role = g.user["role"]
    if role == "chief_lawyer":
        return "cases.chief_dashboard"
    if role == "admin" and any(can(p) for p in MANAGEMENT_PERMISSIONS):
        return "admin.dashboard"
    return "cases.lawyer_dashboard"


@bp.route("/")
def index():
    if g.user is None:
        return redirect(url_for("auth.login"))
    return redirect(url_for(home_endpoint()))


@bp.route("/setup", methods=["GET", "POST"])
def setup_disabled():
    """Mantiene los enlaces antiguos sin exponer un registro de administradores."""
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("auth.index"))
    if request.method == "POST":
        db_path = runtime().settings.db_path
        username = request.form.get("username", "").strip()[:60]
        password = request.form.get("password", "")
        wait = store.lock_remaining(db_path, username)
        if wait:
            audit.record("auth.login", "denied", reason="cuenta bloqueada temporalmente", username=username)
            flash(f"Demasiados intentos fallidos. Espera {wait // 60 + 1} min e inténtalo de nuevo.", "error")
            return render_template("login.html")
        user = user_service.authenticate(db_path, username, password)
        if user is not None:
            store.clear_failed_logins(db_path, username)
            session.clear()
            session["user_id"] = user["id"]
            session["epoch"] = user["session_epoch"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            audit.record("auth.login", "ok", user=user)
            return redirect(url_for("auth.index"))
        store.register_failed_login(db_path, username)
        audit.record("auth.login", "denied", reason="credenciales inválidas", username=username)
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    audit.record("auth.logout", "ok")
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    forced = bool(g.user["must_change_password"])
    if request.method == "POST":
        try:
            epoch = user_service.change_own_password(
                runtime().settings.db_path, g.user["id"], request.form.get("current_password", ""),
                request.form.get("new_password", ""), request.form.get("confirm_password", ""))
        except user_service.UserError as exc:
            audit.record("auth.password_change", "denied", reason=str(exc))
            flash(str(exc), "error")
            return render_template("password.html", forced=forced)
        session["epoch"] = epoch            # esta sesión sigue; las demás quedan invalidadas
        session["csrf_token"] = secrets.token_urlsafe(32)
        audit.record("auth.password_change", "ok")
        flash("Contraseña actualizada. Las demás sesiones abiertas se cerraron.", "success")
        return redirect(url_for("auth.index"))
    return render_template("password.html", forced=forced)
