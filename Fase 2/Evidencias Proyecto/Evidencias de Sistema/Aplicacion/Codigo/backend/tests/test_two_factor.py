"""Doble factor (TOTP) opcional para el administrador y el abogado jefe."""
import time

import pytest

from helpers import CSRF, PASSWORD, _client_as, _web_app, add_user, admin_id
from vexa.security import totp, vault
from vexa.services import users as user_service


@pytest.fixture
def web(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    chief = add_user(web, "jefa", "chief_lawyer")
    with web.connect_db() as db:
        db.execute("UPDATE users SET must_change_password = 0")
    return web, chief


def _client(web, user_id):
    """Cliente con sesión iniciada y la época de sesión vigente (activar 2FA cierra las demás sesiones)."""
    client = _client_as(web, user_id)
    with web.connect_db() as db:
        epoch = db.execute("SELECT session_epoch FROM users WHERE id = ?", (user_id,)).fetchone()[0]
    with client.session_transaction() as session:
        session["epoch"] = epoch
    return client


def _enable(web, user_id, client=None):
    client = client or _client(web, user_id)
    client.post("/account/2fa/start", data={"csrf_token": CSRF})
    with client.session_transaction() as session:
        secret = session["totp_setup"]
    code = totp.code_at(secret, totp.current_step())
    assert client.post("/account/2fa/enable", data={"csrf_token": CSRF, "code": code}).status_code == 302
    return secret, client


def _login(web, username):
    client = web.app.test_client()
    with client.session_transaction() as session:
        session["csrf_token"] = CSRF
    response = client.post("/login", data={"csrf_token": CSRF, "username": username, "password": PASSWORD})
    with client.session_transaction() as session:
        token = session.get("csrf_token")             # el inicio de sesión renueva la sesión y su token
    return client, response, token


def test_rfc6238_reference_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"                 # "12345678901234567890" en base32
    assert totp.code_at(secret, 59 // 30) == "287082"            # RFC 6238, T = 59 s, 6 dígitos
    assert totp.verify(secret, "287 082", now=59) == 1
    assert totp.verify(secret, "287082", last_step=1, now=59) is None   # ya usado
    assert totp.verify(secret, "000000", now=59) is None


def test_enabling_stores_the_secret_encrypted_and_requires_the_code_at_login(web):
    web, chief = web
    secret, _ = _enable(web, chief)
    with web.connect_db() as db:
        row = db.execute("SELECT totp_secret, totp_enabled FROM users WHERE id = ?", (chief,)).fetchone()
    assert row["totp_enabled"] == 1 and row["totp_secret"].startswith(vault.TEXT_PREFIX)
    assert secret not in row["totp_secret"]
    client, response, token = _login(web, "jefa")
    assert response.headers["Location"].endswith("/login/codigo")
    assert client.get("/account").status_code == 302                # aún sin sesión
    with client.session_transaction() as session:
        assert "user_id" not in session
    wrong = client.post("/login/codigo", data={"csrf_token": token, "code": "000000"})
    assert "no es correcto" in wrong.get_data(as_text=True)
    ok = client.post("/login/codigo", data={"csrf_token": token, "code": totp.code_at(secret, totp.current_step() + 1)})
    assert ok.status_code == 302 and not ok.headers["Location"].endswith("/login")
    with client.session_transaction() as session:
        assert session["user_id"] == chief


def test_a_code_cannot_be_reused(web):
    web, chief = web
    secret, _ = _enable(web, chief)
    code = totp.code_at(secret, totp.current_step() + 1)
    assert user_service.check_two_factor(web.db_path, chief, code) is True
    assert user_service.check_two_factor(web.db_path, chief, code) is False


def test_pending_code_step_expires(web):
    web, chief = web
    _enable(web, chief)
    client, _, _ = _login(web, "jefa")
    with client.session_transaction() as session:
        session["pending_2fa"]["at"] = int(time.time()) - 600
        session.modified = True
    assert client.get("/login/codigo").headers["Location"].endswith("/login")


def test_wrong_code_at_enrollment_and_lawyers_cannot_enable(web):
    web, chief = web
    client = _client_as(web, chief)
    client.post("/account/2fa/start", data={"csrf_token": CSRF})
    client.post("/account/2fa/enable", data={"csrf_token": CSRF, "code": "123456"})
    assert not user_service.two_factor_enabled(web.db_path, chief)
    lawyer = add_user(web, "luis")
    lawyer_client = _client_as(web, lawyer)
    lawyer_client.post("/account/2fa/start", data={"csrf_token": CSRF})
    with lawyer_client.session_transaction() as session:
        assert "totp_setup" not in session
    assert 'id="doble-factor"' not in lawyer_client.get("/account").get_data(as_text=True)


def test_disable_needs_password_and_admin_can_reset_others(web):
    web, chief = web
    _, client = _enable(web, chief)
    client.post("/account/2fa/disable", data={"csrf_token": CSRF, "current_password": "otra-clave-mala"})
    assert user_service.two_factor_enabled(web.db_path, chief)
    client.post("/account/2fa/disable", data={"csrf_token": CSRF, "current_password": PASSWORD})
    assert not user_service.two_factor_enabled(web.db_path, chief)

    _enable(web, chief)
    admin = _client(web, admin_id(web))
    assert "Quitar doble factor" in admin.get("/admin?tab=usuarios").get_data(as_text=True)
    admin.post(f"/admin/users/{chief}/2fa/reset", data={"csrf_token": CSRF})
    assert not user_service.two_factor_enabled(web.db_path, chief)
    _enable(web, chief)
    _client(web, chief).post(f"/admin/users/{admin_id(web)}/2fa/reset", data={"csrf_token": CSRF})
    with web.connect_db() as db:
        actions = [r[0] for r in db.execute("SELECT result FROM audit_log WHERE action = 'users.2fa_reset' ORDER BY id")]
    assert actions[0] == "ok" and actions[-1] == "denied"


def test_cli_removes_two_factor(web, monkeypatch):
    import quitar_doble_factor
    web, chief = web
    _enable(web, chief)
    monkeypatch.setattr(quitar_doble_factor, "load_settings", lambda: web.settings)
    assert quitar_doble_factor.main(["jefa"]) == 0
    assert not user_service.two_factor_enabled(web.db_path, chief)
