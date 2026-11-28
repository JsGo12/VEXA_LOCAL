"""Pruebas de seguridad heredadas (rutas protegidas, bloqueo de login, vault), adaptadas a la app modular."""
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import InvalidToken

from helpers import CSRF, PASSWORD, _client_as, _seed_case, _web_app, add_user  # noqa: F401  (reexportados)
from vexa.config import ConfigError, load_settings
from vexa.database import store
from vexa.security import vault


def test_unassigned_lawyer_cannot_open_download_or_use_case_apis(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _assigned_id, other_id, case_id, document_id = _seed_case(web, tmp_path)
    client = _client_as(web, other_id)

    protected_gets = [
        f"/case/{case_id}",
        f"/documents/{document_id}",
        f"/api/case/{case_id}/status",
        f"/api/case/{case_id}/history",
        f"/api/case/{case_id}/summary",
    ]
    for path in protected_gets:
        assert client.get(path).status_code == 403, path

    protected_posts = [
        (f"/api/case/{case_id}/history/clear", {}),
        (f"/api/case/{case_id}/chat", {"question": "¿Qué dice el contrato?"}),
    ]
    for path, payload in protected_posts:
        response = client.post(path, json=payload, headers={"X-CSRF-Token": CSRF})
        assert response.status_code == 403, path


def test_assigned_lawyer_can_open_and_download_case_documents(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    assigned_id, _other_id, case_id, document_id = _seed_case(web, tmp_path)
    client = _client_as(web, assigned_id)

    assert client.get(f"/case/{case_id}").status_code == 200
    download = client.get(f"/documents/{document_id}")
    assert download.status_code == 200
    assert download.data == b"Texto de prueba del contrato."
    assert client.get(f"/api/case/{case_id}/status").status_code == 200


def test_lawyer_cannot_use_admin_routes(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _assigned_id, other_id, _case_id, _document_id = _seed_case(web, tmp_path)
    client = _client_as(web, other_id)

    assert client.get("/admin").status_code == 403
    for path in ("/admin/users", "/admin/teams", "/admin/cases"):
        response = client.post(path, data={}, headers={"X-CSRF-Token": CSRF})
        assert response.status_code == 403, path


def test_external_bind_host_is_rejected_by_configuration():
    """Antes VEXA_HOST se ignoraba en silencio; ahora un valor no-loopback detiene el arranque."""
    for host in ("0.0.0.0", "::", "192.168.1.10"):
        with pytest.raises(ConfigError, match="loopback"):
            load_settings({"VEXA_HOST": host}, use_env_file=False)
    assert load_settings({"VEXA_HOST": "127.0.0.1", "VEXA_PORT": "51234"}, use_env_file=False).port == 51234


def test_setup_creates_at_most_one_admin_under_concurrent_requests(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)

    def submit_setup(username):
        client = web.app.test_client()
        with client.session_transaction() as session:
            session["csrf_token"] = CSRF
        return client.post("/setup", data={"name": username, "username": username,
                                           "password": PASSWORD, "csrf_token": CSRF}).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(submit_setup, ("admin_uno", "admin_dos")))

    with web.connect_db() as db:
        admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    assert admins == 1
    assert statuses.count(302) == 2


def test_login_lockout_blocks_even_a_correct_password(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    add_user(web, "ana")
    client = web.app.test_client()
    with client.session_transaction() as session:
        session["csrf_token"] = CSRF

    for _ in range(store.MAX_FAILED):
        client.post("/login", data={"username": "ana", "password": "incorrecta", "csrf_token": CSRF})

    locked = client.post("/login", data={"username": "ana", "password": PASSWORD, "csrf_token": CSRF})
    assert b"Demasiados intentos" in locked.data
    with client.session_transaction() as session:
        assert "user_id" not in session


def test_post_without_csrf_token_is_rejected(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    assigned_id, _other, case_id, _doc = _seed_case(web)
    client = _client_as(web, assigned_id)
    response = client.post(f"/api/case/{case_id}/history/clear", json={})
    assert response.status_code == 400


def test_new_windows_vault_key_fails_closed_if_dpapi_fails(monkeypatch, tmp_path):
    vault.configure(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")

    def fail_dpapi(_data, _protect):
        raise OSError("DPAPI no disponible")

    monkeypatch.setattr(vault, "_dpapi", fail_dpapi)
    with pytest.raises(OSError, match="DPAPI"):
        vault.encrypt_bytes(b"dato secreto")
    assert not (tmp_path / "vault.key").exists()


def test_legacy_windows_vault_key_is_upgraded_without_changing_data(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    key_path = tmp_path / "vault.key"
    key_path.write_bytes(key)
    ciphertext = vault.MAGIC + Fernet(key).encrypt(b"dato antiguo")
    vault.configure(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")

    def fake_dpapi(data, protect):
        return b"wrapped:" + data if protect else data.removeprefix(b"wrapped:")

    monkeypatch.setattr(vault, "_dpapi", fake_dpapi)
    assert vault.decrypt_bytes(ciphertext) == b"dato antiguo"
    assert key_path.read_bytes() == b"DPAPI:wrapped:" + key


def test_session_secret_is_stored_encrypted(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    stored = (web.data_dir / "web_secret.key").read_text(encoding="utf-8")
    assert stored.startswith(vault.TEXT_PREFIX)
    assert vault.dec_text(stored) == web.app.secret_key


def test_encrypted_document_survives_vault_reconfiguration(tmp_path):
    vault.configure(tmp_path)
    ciphertext = vault.encrypt_bytes(b"contenido recuperable")

    vault.configure(tmp_path)

    assert vault.decrypt_bytes(ciphertext) == b"contenido recuperable"


def test_corrupt_encrypted_document_fails_closed(tmp_path):
    vault.configure(tmp_path)
    ciphertext = vault.encrypt_bytes(b"contenido privado")

    # Trimming only the last base64 character can preserve the decoded token
    # when it consists solely of unused padding bits.
    with pytest.raises(InvalidToken):
        vault.decrypt_bytes(ciphertext[:-10])
