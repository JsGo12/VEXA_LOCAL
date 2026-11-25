"""Cierre de sesión por inactividad (VEXA_IDLE_MINUTES)."""
import time

import pytest

from helpers import CSRF, _client_as, _web_app, admin_id
from vexa.config import ConfigError, load_settings


@pytest.fixture
def web(monkeypatch, tmp_path):
    return _web_app(monkeypatch, tmp_path, idle_minutes=60)


def _idle_for(client, seconds):
    with client.session_transaction() as session:
        session["last_seen"] = int(time.time()) - seconds


def test_idle_session_is_closed_and_audited(web):
    client = _client_as(web, admin_id(web))
    _idle_for(client, 61 * 60)
    response = client.get("/admin")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    assert "cerró por inactividad" in client.get("/login").get_data(as_text=True)
    assert client.get("/admin").status_code == 302                       # ya no hay sesión
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.session_expired'").fetchone()[0] == 1


def test_api_gets_401_json_when_expired(web):
    client = _client_as(web, admin_id(web))
    _idle_for(client, 61 * 60)
    response = client.get("/api/notificaciones/contador", headers={"X-Vexa-Background": "1"})
    assert response.status_code == 401 and response.get_json()["expired"] is True


def test_background_polling_does_not_keep_the_session_alive(web):
    client = _client_as(web, admin_id(web))
    _idle_for(client, 30 * 60)
    assert client.get("/api/notificaciones/contador", headers={"X-Vexa-Background": "1"}).status_code == 200
    with client.session_transaction() as session:
        assert int(time.time()) - session["last_seen"] >= 30 * 60        # no se renovó
    assert client.get("/admin").status_code == 200                       # uso real: sí renueva
    with client.session_transaction() as session:
        assert int(time.time()) - session["last_seen"] < 5


def test_page_activity_ping_and_explicit_expiry(web):
    client = _client_as(web, admin_id(web))
    _idle_for(client, 50 * 60)
    assert client.post("/api/sesion/activa", headers={"X-CSRF-Token": CSRF}).get_json() == {"ok": True}
    with client.session_transaction() as session:
        assert int(time.time()) - session["last_seen"] < 5
    assert client.post("/api/sesion/expirar", headers={"X-CSRF-Token": CSRF}).status_code == 200
    assert client.get("/admin").status_code == 302


def test_zero_disables_the_idle_logout(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path, idle_minutes=0)
    client = _client_as(web, admin_id(web))
    _idle_for(client, 10 * 24 * 3600)
    assert client.get("/admin").status_code == 200
    assert 'name="vexa-idle-seconds"' not in client.get("/admin").get_data(as_text=True)


def test_idle_minutes_setting_is_validated():
    assert load_settings({}, use_env_file=False).idle_minutes == 60
    assert load_settings({"VEXA_IDLE_MINUTES": "15"}, use_env_file=False).idle_minutes == 15
    with pytest.raises(ConfigError):
        load_settings({"VEXA_IDLE_MINUTES": "-1"}, use_env_file=False)
