"""Inicio de sesión, cierre de sesión y redirección según el perfil."""
from __future__ import annotations

import secrets
import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from vexa import runtime
from vexa.database import connect, store
from vexa.permissions import MANAGEMENT_PERMISSIONS, can, login_required, policy
from vexa.permissions.catalog import PERMISSIONS
from vexa.security import totp
from vexa.services import audit
from vexa.services import cases as case_service
from vexa.services import users as user_service

bp = Blueprint("auth", __name__)
PENDING_2FA_SECONDS = 5 * 60        # tiempo para escribir el código tras la contraseña


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
        if user is not None and user["totp_enabled"]:
            # Contraseña correcta, falta el código de la app: aún no hay sesión iniciada.
            session.clear()
            session["pending_2fa"] = {"uid": user["id"], "username": user["username"], "at": int(time.time())}
            session["csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("auth.login_code"))
        if user is not None:
            store.clear_failed_logins(db_path, username)
            _start_session(user)
            audit.record("auth.login", "ok", user=user)
            return redirect(url_for("auth.index"))
        store.register_failed_login(db_path, username)
        audit.record("auth.login", "denied", reason="credenciales inválidas", username=username)
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


def _start_session(user) -> None:
    session.clear()
    session["user_id"] = user["id"]
    session["epoch"] = user["session_epoch"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    session["last_seen"] = int(time.time())
    session.permanent = True


@bp.route("/login/codigo", methods=["GET", "POST"])
def login_code():
    """Segundo paso del inicio de sesión: el código de 6 dígitos de la app de autenticación."""
    pending = session.get("pending_2fa")
    if g.user:
        return redirect(url_for("auth.index"))
    if not pending or int(time.time()) - pending.get("at", 0) > PENDING_2FA_SECONDS:
        session.pop("pending_2fa", None)
        flash("Vuelve a escribir tu usuario y contraseña.", "error")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        db_path = runtime().settings.db_path
        username = pending["username"]
        wait = store.lock_remaining(db_path, username)
        if wait:
            session.pop("pending_2fa", None)
            audit.record("auth.login", "denied", reason="cuenta bloqueada temporalmente", username=username)
            flash(f"Demasiados intentos fallidos. Espera {wait // 60 + 1} min e inténtalo de nuevo.", "error")
            return redirect(url_for("auth.login"))
        if user_service.check_two_factor(db_path, pending["uid"], request.form.get("code", "")):
            with connect(db_path) as db:
                user = db.execute("SELECT * FROM users WHERE id = ? AND active = 1", (pending["uid"],)).fetchone()
            if user is not None:
                store.clear_failed_logins(db_path, username)
                _start_session(user)
                audit.record("auth.login", "ok", user=user, details={"doble_factor": True})
                return redirect(url_for("auth.index"))
        store.register_failed_login(db_path, username)
        audit.record("auth.login", "denied", reason="código de verificación incorrecto", username=username)
        flash("El código no es correcto o ya se usó. Espera el siguiente código de la app.", "error")
    return render_template("login_code.html")


@bp.post("/account/2fa/start")
@login_required
def two_factor_start():
    """Genera una clave nueva (aún no activa) para que la persona la agregue a su app."""
    if g.user["role"] not in user_service.TWO_FACTOR_ROLES:
        flash("El doble factor está disponible para el administrador y el abogado jefe.", "error")
        return redirect(url_for("auth.profile"))
    session["totp_setup"] = totp.new_secret()
    return redirect(url_for("auth.profile") + "#doble-factor")


@bp.post("/account/2fa/enable")
@login_required
def two_factor_enable():
    secret = session.get("totp_setup")
    if not secret or g.user["role"] not in user_service.TWO_FACTOR_ROLES:
        flash("Primero genera la clave del doble factor.", "error")
        return redirect(url_for("auth.profile") + "#doble-factor")
    try:
        epoch = user_service.enable_two_factor(runtime().settings.db_path, g.user["id"], secret,
                                               request.form.get("code", ""))
    except user_service.UserError as exc:
        audit.record("auth.2fa_enable", "denied", reason="código incorrecto")
        flash(str(exc), "error")
        return redirect(url_for("auth.profile") + "#doble-factor")
    session.pop("totp_setup", None)
    session["epoch"] = epoch            # esta sesión sigue; las demás se cierran
    audit.record("auth.2fa_enable", "ok")
    flash("Doble factor activado. Desde ahora VEXA te pedirá el código de la app al iniciar sesión.", "success")
    return redirect(url_for("auth.profile") + "#doble-factor")


@bp.post("/account/2fa/disable")
@login_required
def two_factor_disable():
    db_path = runtime().settings.db_path
    if not user_service.verify_password(db_path, g.user["id"], request.form.get("current_password", "")):
        audit.record("auth.2fa_disable", "denied", reason="contraseña incorrecta")
        flash("La contraseña no es correcta.", "error")
        return redirect(url_for("auth.profile") + "#doble-factor")
    session["epoch"] = user_service.disable_two_factor(db_path, g.user["id"])
    audit.record("auth.2fa_disable", "ok")
    flash("Doble factor desactivado.", "success")
    return redirect(url_for("auth.profile") + "#doble-factor")


@bp.post("/logout")
@login_required
def logout():
    audit.record("auth.logout", "ok")
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def profile():
    """Mi perfil: datos de la cuenta, nombre visible, casos, actividad, permisos y seguridad."""
    settings = runtime().settings
    if request.method == "POST":
        try:
            user_service.update_own_name(settings.db_path, g.user["id"], request.form.get("name", ""))
            audit.record("users.profile_update", "ok", resource_type="user", resource_id=g.user["id"])
            flash("Nombre actualizado.", "success")
        except user_service.UserError as exc:
            flash(str(exc), "error")
        return redirect(url_for("auth.profile"))
    with connect(settings.db_path) as db:
        perms = policy.effective_permissions(db, g.user)
        scope = policy.case_scope(db, g.user) if "cases.view" in perms else {}
    follow = case_service.follow_up(settings.db_path, case_ids=scope)
    return render_template(
        "profile.html", details=user_service.profile_details(settings.db_path, g.user["id"]),
        cases=follow["cases"][:6], total_cases=len(follow["cases"]),
        overdue=len(follow["overdue"]), due_soon=len(follow["due_soon"]),
        permissions=[(p, PERMISSIONS[p]) for p in PERMISSIONS if p in perms],
        two_factor=_two_factor_view(settings.db_path))


def _two_factor_view(db_path) -> dict:
    """Datos de la tarjeta Doble factor del perfil (la clave solo mientras se está activando)."""
    allowed = g.user["role"] in user_service.TWO_FACTOR_ROLES
    enabled = allowed and user_service.two_factor_enabled(db_path, g.user["id"])
    secret = session.get("totp_setup") if allowed and not enabled else None
    return {"allowed": allowed, "enabled": enabled,
            "secret": totp.grouped(secret) if secret else None}


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    forced = bool(g.user["must_change_password"])
    from_profile = request.form.get("next") == "profile" and not forced   # solo destino fijo, sin redirección abierta
    if request.method == "POST":
        try:
            epoch = user_service.change_own_password(
                runtime().settings.db_path, g.user["id"], request.form.get("current_password", ""),
                request.form.get("new_password", ""), request.form.get("confirm_password", ""))
        except user_service.UserError as exc:
            audit.record("auth.password_change", "denied", reason=str(exc))
            flash(str(exc), "error")
            if from_profile:
                return redirect(url_for("auth.profile") + "#seguridad")
            return render_template("password.html", forced=forced)
        session["epoch"] = epoch            # esta sesión sigue; las demás quedan invalidadas
        session["csrf_token"] = secrets.token_urlsafe(32)
        audit.record("auth.password_change", "ok")
        flash("Contraseña actualizada. Las demás sesiones abiertas se cerraron.", "success")
        return redirect(url_for("auth.profile") if from_profile else url_for("auth.index"))
    return render_template("password.html", forced=forced)
