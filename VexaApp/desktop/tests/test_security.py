import importlib
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import InvalidToken
from werkzeug.security import generate_password_hash

import vault
import store


CSRF = "test-csrf-token"


def _web_app(monkeypatch, tmp_path, disable_background_index=True):
    """Import Flask under a temporary profile so tests never touch user data."""
    profile = tmp_path.parent / "test-profile"
    profile.mkdir(exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(profile))
    web = importlib.import_module("web_app")
    monkeypatch.setattr(web, "DB_PATH", tmp_path / "web.db")
    web.vault.configure(web.DATA_DIR)
    web.initialize_db()
    web.store.init(web.DB_PATH)
    if disable_background_index:
        monkeypatch.setattr(web, "_precargar_indice", lambda _case_id: None)
    return web


def _seed_case(web, tmp_path):
    document_path = tmp_path / "contract.txt.enc"
    vault.write_encrypted(document_path, b"Texto de prueba del contrato.")
    with web.connect_db() as db:
        db.execute(
            "INSERT INTO users(name, username, password_hash, role) VALUES (?, ?, ?, 'lawyer')",
            ("Abogada asignada", "asignada", generate_password_hash("ContrasenaSegura123")),
        )
        assigned_id = db.execute("SELECT id FROM users WHERE username='asignada'").fetchone()[0]
        db.execute(
            "INSERT INTO users(name, username, password_hash, role) VALUES (?, ?, ?, 'lawyer')",
            ("Abogado ajeno", "ajeno", generate_password_hash("ContrasenaSegura456")),
        )
        other_id = db.execute("SELECT id FROM users WHERE username='ajeno'").fetchone()[0]
        db.execute(
            "INSERT INTO cases(title, summary, reference, due_at, created_by) VALUES (?, '', '', ?, ?)",
            ("Caso privado", "2099-01-01T00:00", assigned_id),
        )
        case_id = db.execute("SELECT id FROM cases").fetchone()[0]
        db.execute("INSERT INTO case_assignments(case_id, user_id) VALUES (?, ?)", (case_id, assigned_id))
        db.execute(
            "INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (case_id, "contrato.txt", str(document_path), "test-hash", assigned_id),
        )
        document_id = db.execute("SELECT id FROM documents").fetchone()[0]
    return assigned_id, other_id, case_id, document_id


def _client_as(web, user_id):
    client = web.app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["csrf_token"] = CSRF
    return client


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


def test_development_backend_ignores_external_bind_host(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    calls = {}
    monkeypatch.setenv("VEXA_HOST", "0.0.0.0")
    monkeypatch.setenv("VEXA_PORT", "51234")
    monkeypatch.setattr(web, "start_background_services", lambda: None)
    monkeypatch.setattr(web.app, "run", lambda **kwargs: calls.update(kwargs))

    web.run_local_server()

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 51234
    assert calls["debug"] is False


def test_setup_creates_at_most_one_admin_under_concurrent_requests(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)

    def submit_setup(username):
        client = web.app.test_client()
        with client.session_transaction() as session:
            session["csrf_token"] = CSRF
        return client.post(
            "/setup",
            data={
                "name": username,
                "username": username,
                "password": "ContrasenaSegura123",
                "csrf_token": CSRF,
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(submit_setup, ("admin_uno", "admin_dos")))

    with web.connect_db() as db:
        admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    assert admins == 1
    assert statuses.count(302) == 2


def test_login_lockout_blocks_even_a_correct_password(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    with web.connect_db() as db:
        db.execute(
            "INSERT INTO users(name, username, password_hash, role) VALUES (?, ?, ?, 'lawyer')",
            ("Abogada", "ana", generate_password_hash("ContrasenaSegura123")),
        )
    client = web.app.test_client()
    with client.session_transaction() as session:
        session["csrf_token"] = CSRF

    for _ in range(store.MAX_FAILED):
        client.post("/login", data={"username": "ana", "password": "incorrecta", "csrf_token": CSRF})

    locked = client.post("/login", data={"username": "ana", "password": "ContrasenaSegura123", "csrf_token": CSRF})
    assert b"Demasiados intentos" in locked.data
    with client.session_transaction() as session:
        assert "user_id" not in session


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
    stored = (web.DATA_DIR / "web_secret.key").read_text(encoding="utf-8")
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
