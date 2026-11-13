"""Arquitectura, configuración (.env), Waitress, red/Tailscale, migraciones, cifrado y auditoría."""
import importlib
import io
import pkgutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import vexa
from helpers import CSRF, PASSWORD, _client_as, _seed_case, _web_app, add_user, admin_id, make_settings
from vexa import server
from vexa.config import ConfigError, PROJECT_DIR, load_settings, read_env_file
from vexa.database import migrations
from vexa.security import network, vault

BACKEND = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ arquitectura
def test_every_backend_module_imports_without_cycles():
    for info in pkgutil.walk_packages(vexa.__path__, "vexa."):
        importlib.import_module(info.name)


def test_backend_starts_and_serves_health_and_static(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    client = web.app.test_client()
    assert client.get("/health").get_json() == {"ok": True, "app": "vexa"}
    assert client.get("/static/css/base.css").status_code == 200
    assert client.get("/static/js/case-chat.js").status_code == 200
    login = client.get("/login")
    assert login.status_code == 200
    assert "script-src 'self'" in login.headers["Content-Security-Policy"]
    assert login.headers["X-Frame-Options"] == "DENY"


def test_data_directory_is_not_exposed_through_static_routes(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    client = web.app.test_client()
    for path in ("/static/../../vexa_web.db", "/static/%2e%2e/%2e%2e/backend/run.py", "/static/vault.key"):
        assert client.get(path).status_code == 404, path


def test_frontend_contains_no_inline_scripts_or_styles():
    templates = (PROJECT_DIR / "frontend" / "templates").glob("*.html")
    for template in templates:
        text = template.read_text(encoding="utf-8")
        assert "<script>" not in text, template.name
        assert "style=" not in text, template.name


# ---------------------------------------------------------------- configuración
def test_env_example_is_complete_and_valid(tmp_path):
    example = PROJECT_DIR / ".env.example"
    values = read_env_file(example)
    for key in ("VEXA_ENV", "VEXA_HOST", "VEXA_PORT", "VEXA_SECRET_KEY", "VEXA_DATA_DIR", "VEXA_DB_PATH",
                "VEXA_LOG_LEVEL", "VEXA_SERVER", "OLLAMA_HOST", "TAILSCALE_ENABLED", "TAILSCALE_BIND_ADDRESS",
                "VEXA_SESSION_COOKIE_SECURE"):
        assert key in values, key
    assert not values["VEXA_SECRET_KEY"], ".env.example no debe traer secretos"
    settings = load_settings({}, env_file=example)
    assert settings.host == "127.0.0.1" and settings.tailscale_enabled is False


def test_env_file_is_loaded_and_process_environment_wins(tmp_path):
    env = tmp_path / ".env"
    env.write_text("VEXA_PORT=5100\nVEXA_LOG_LEVEL=warning\nVEXA_THREADS=4\n", encoding="utf-8")
    settings = load_settings({"VEXA_PORT": "5200"}, env_file=env)
    assert settings.port == 5200 and settings.log_level == "WARNING" and settings.threads == 4
    assert settings.env_file == env


def test_real_env_file_is_ignored_by_git():
    if not (PROJECT_DIR / ".env").exists():
        pytest.skip("no hay .env local")
    result = subprocess.run(["git", "check-ignore", "-q", str(PROJECT_DIR / ".env")], cwd=PROJECT_DIR)
    assert result.returncode == 0, ".env debe estar ignorado por Git"


@pytest.mark.parametrize("env,match", [
    ({"OLLAMA_HOST": "http://10.0.0.5:11434"}, "OLLAMA_HOST"),
    ({"OLLAMA_HOST": "https://api.example.com"}, "OLLAMA_HOST"),
    ({"VEXA_SECRET_KEY": "corta"}, "VEXA_SECRET_KEY"),
    ({"VEXA_ENV": "production", "VEXA_SERVER": "flask"}, "producción|production"),
    ({"VEXA_PORT": "99999"}, "VEXA_PORT"),
    ({"TAILSCALE_ENABLED": "quizas"}, "TAILSCALE_ENABLED"),
    ({"TAILSCALE_BIND_ADDRESS": "0.0.0.0"}, "TAILSCALE_BIND_ADDRESS"),
    ({"TAILSCALE_BIND_ADDRESS": "192.168.1.20"}, "TAILSCALE_BIND_ADDRESS"),
])
def test_invalid_configuration_is_rejected(env, match):
    with pytest.raises(ConfigError, match=match):
        load_settings(env, use_env_file=False)


def test_settings_repr_and_summary_hide_secrets():
    settings = load_settings({"VEXA_SECRET_KEY": "x" * 40, "VEXA_ADMIN_PASSWORD": "y" * 14}, use_env_file=False)
    assert "x" * 40 not in repr(settings) and "y" * 14 not in repr(settings)
    assert settings.safe_summary()["secret_key"] == "<definida>"


def test_flask_secret_from_env_is_separate_from_document_key(monkeypatch, tmp_path):
    secret = "s" * 48
    web = _web_app(monkeypatch, tmp_path, secret_key=secret)
    assert web.app.secret_key == secret
    assert not (web.data_dir / "web_secret.key").exists()       # no reemplaza ni crea otra clave
    key_file = (web.data_dir / "vault.key")
    vault.encrypt_bytes(b"x")
    assert key_file.exists() and secret.encode() not in key_file.read_bytes()


def test_check_command_validates_without_starting(tmp_path):
    env = tmp_path / "check.env"
    env.write_text(f"VEXA_DATA_DIR={tmp_path / 'datos'}\nVEXA_PORT=5333\n", encoding="utf-8")
    import os
    child_env = {k: v for k, v in os.environ.items() if not k.startswith(("VEXA_", "TAILSCALE_", "OLLAMA_"))}
    child_env.update(VEXA_ENV_FILE=str(env), USERPROFILE=str(tmp_path), HOME=str(tmp_path))
    result = subprocess.run([sys.executable, str(BACKEND / "run.py"), "--check"], capture_output=True, text=True,
                            env=child_env, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:5333" in result.stdout
    assert not (tmp_path / "datos").exists()


# --------------------------------------------------------------- red / Tailscale
def test_local_mode_listens_only_on_loopback():
    settings = load_settings({}, use_env_file=False)
    assert network.listen_addresses(settings, detect=lambda: pytest.fail("no debe detectar")) == [("127.0.0.1", 5000)]


def test_tailscale_enabled_adds_only_the_tailscale_address():
    settings = load_settings({"TAILSCALE_ENABLED": "true", "TAILSCALE_BIND_ADDRESS": "100.101.102.103",
                              "TAILSCALE_PORT": "5443"}, use_env_file=False)
    listeners = network.listen_addresses(settings)
    assert listeners == [("127.0.0.1", 5000), ("100.101.102.103", 5443)]
    assert network.format_listen(listeners) == "127.0.0.1:5000 100.101.102.103:5443"
    assert all(host not in {"0.0.0.0", "::"} for host, _ in listeners)


def test_tailscale_autodetection_and_failure():
    settings = load_settings({"TAILSCALE_ENABLED": "true"}, use_env_file=False)
    assert network.listen_addresses(settings, detect=lambda: "100.64.0.7")[1] == ("100.64.0.7", 5000)
    with pytest.raises(ConfigError, match="Tailscale"):
        network.listen_addresses(settings, detect=lambda: None)
    with pytest.raises(ConfigError, match="rango"):
        network.listen_addresses(settings, detect=lambda: "8.8.8.8")


def test_tailscale_interface_detection_requires_tailscale_interface():
    from types import SimpleNamespace as A
    # Docker: sin CLI, la IP sale de tailscale0 (red compartida con el contenedor de Tailscale).
    assert network.tailscale_interface_ipv4({
        "eth0": [A(address="172.18.0.2")],
        "tailscale0": [A(address="fd7a:115c:a1e0::1"), A(address="100.90.1.2")],
    }) == "100.90.1.2"
    # Una IP CGNAT del proveedor (también 100.64.0.0/10) en otra interfaz NO se usa.
    assert network.tailscale_interface_ipv4({"eth0": [A(address="100.70.0.5")]}) is None


def test_docker_files_keep_the_network_policy():
    def code(name):  # sin comentarios: solo lo que Docker ejecuta
        lines = (BACKEND.parent / name).read_text(encoding="utf-8").splitlines()
        return "\n".join(line.split("#")[0] for line in lines)

    compose, dockerfile = code("docker-compose.yml"), code("Dockerfile")
    assert "0.0.0.0" not in dockerfile and "0.0.0.0" not in compose
    # Sin puertos publicados: solo se entra por Tailscale; Ollama solo en loopback.
    assert "ports:" not in compose
    assert "OLLAMA_HOST: 127.0.0.1:11434" in compose
    assert compose.count("network_mode: service:tailscale") == 2
    dockerignore = (BACKEND.parent / ".dockerignore").read_text(encoding="utf-8").split()
    assert ".env" in dockerignore and ".venv" in dockerignore


def test_remote_address_filter():
    calls = []
    app = network.RemoteAddressFilter(lambda env, start: calls.append(env) or [b"ok"], allow_tailscale=False)
    status = []
    start = lambda s, h: status.append(s)  # noqa: E731
    assert app({"REMOTE_ADDR": "127.0.0.1"}, start) == [b"ok"]
    app({"REMOTE_ADDR": "192.168.1.50"}, start)
    app({"REMOTE_ADDR": "100.100.1.1"}, start)
    assert status == ["403 Forbidden", "403 Forbidden"] and len(calls) == 1
    ts = network.RemoteAddressFilter(lambda env, start: [b"ok"], allow_tailscale=True)
    assert ts({"REMOTE_ADDR": "100.100.1.1"}, start) == [b"ok"]
    assert ts({"REMOTE_ADDR": "fd7a:115c:a1e0::1"}, start) == [b"ok"]
    ts({"REMOTE_ADDR": "203.0.113.9"}, start)
    assert status[-1] == "403 Forbidden"


def test_requests_from_other_networks_are_rejected_by_the_app(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    client = web.app.test_client()
    assert client.get("/health", environ_base={"REMOTE_ADDR": "192.168.0.20"}).status_code == 403
    assert client.get("/health", environ_base={"REMOTE_ADDR": "100.90.1.2"}).status_code == 403  # Tailscale apagado
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400              # TRUSTED_HOSTS


def test_waitress_is_used_with_validated_listeners(monkeypatch, tmp_path):
    calls = {}
    import waitress
    monkeypatch.setattr(waitress, "serve", lambda app, **kw: calls.update(kw))
    settings = make_settings(tmp_path, port=5444, threads=6)
    assert server.serve(settings) == 0
    assert calls["listen"] == "127.0.0.1:5444" and calls["threads"] == 6
    assert not (settings.data_dir / server.INFO_NAME).exists()     # se limpia al terminar


def test_flask_dev_server_never_binds_outside_loopback(monkeypatch, tmp_path):
    calls = {}
    import flask
    monkeypatch.setattr(flask.Flask, "run", lambda self, **kw: calls.update(kw))
    settings = make_settings(tmp_path, port=5445, tailscale_enabled=True, tailscale_bind_address="100.64.1.1")
    assert server.serve(settings, dev=True) == 0
    assert calls["host"] == "127.0.0.1" and calls["port"] == 5445 and calls["debug"] is False


def test_second_server_on_same_data_dir_is_refused(tmp_path):
    first = server.InstanceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(server.AlreadyRunning):
            server.InstanceLock(tmp_path).acquire()
        settings = make_settings(tmp_path)
        lock_dir_settings = settings.__class__(**{**settings.__dict__, "data_dir": tmp_path})
        assert server.serve(lock_dir_settings) == server.EXIT_ALREADY_RUNNING
    finally:
        first.release()


# ------------------------------------------------------------------ migraciones
LEGACY_SCHEMA = migrations.BASE_SCHEMA.replace("    summary TEXT NOT NULL DEFAULT '',\n", "")


def test_legacy_database_is_migrated_without_losing_data(tmp_path):
    db_path = tmp_path / "vexa_web.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("INSERT INTO users(name, username, password_hash, role) VALUES ('A', 'admin', 'h', 'admin')")
        db.execute("INSERT INTO users(name, username, password_hash, role) VALUES ('L', 'luis', 'h', 'lawyer')")
        db.execute("INSERT INTO cases(title, reference, due_at, created_by) VALUES ('Caso', '', '2099-01-01T00:00', 1)")
        db.execute("INSERT INTO case_assignments(case_id, user_id) VALUES (1, 2)")
        db.execute("INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by) "
                   "VALUES (1, 'a.txt', 'x', 'h', 1)")
    backup = migrations.migrate(db_path, tmp_path / "backups")
    assert backup is not None and backup.exists()
    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST_VERSION
        assert db.execute("SELECT id, role FROM users ORDER BY id").fetchall() == [(1, "admin"), (2, "lawyer")]
        assert db.execute("SELECT user_id FROM case_assignments").fetchone()[0] == 2
        assert db.execute("SELECT restricted FROM documents").fetchone()[0] == 0
        assert db.execute("SELECT user_id, scope_type FROM access_grants").fetchall() == [(1, "firm")]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        db.execute("INSERT INTO users(name, username, password_hash, role) VALUES ('J', 'jefa', 'h', 'chief_lawyer')")
    with sqlite3.connect(backup) as old:
        assert old.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    assert migrations.migrate(db_path, tmp_path / "backups") is None      # idempotente: sin nuevo respaldo


def test_failed_migration_rolls_back(monkeypatch, tmp_path):
    db_path = tmp_path / "vexa_web.db"
    def boom(db):
        db.execute("CREATE TABLE should_not_exist(x)")
        raise RuntimeError("falla simulada")
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1] + [(2, "falla", boom)])
    with pytest.raises(RuntimeError):
        migrations.migrate(db_path, tmp_path / "b")
    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='should_not_exist'").fetchone() is None


# ---------------------------------------------------------------------- cifrado
def test_new_uploads_are_encrypted_and_old_plaintext_documents_remain_readable(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    client = _client_as(web, admin_id(web))
    lawyer = add_user(web, "luis")
    response = client.post("/admin/cases", data={
        "csrf_token": CSRF, "title": "Caso nuevo", "summary": "Resumen", "due_at": "2099-05-01T10:00",
        "assignment_type": "user", "assignee_id": str(lawyer),
        "documents": (io.BytesIO(b"Contenido confidencial nuevo"), "nuevo.txt"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with web.connect_db() as db:
        stored = db.execute("SELECT id, stored_path FROM documents").fetchone()
    raw = Path(stored["stored_path"]).read_bytes()
    assert raw.startswith(vault.MAGIC) and b"confidencial" not in raw
    assert client.get(f"/documents/{stored['id']}").data == b"Contenido confidencial nuevo"
    legacy = tmp_path / "legacy.txt"
    legacy.write_bytes(b"documento antiguo sin cifrar")
    assert vault.read_bytes(legacy) == b"documento antiguo sin cifrar"


def test_existing_vault_key_is_reused_not_replaced(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    key = Fernet.generate_key()
    (data / "vault.key").write_bytes(key)
    monkeypatch.setattr(sys, "platform", "linux")       # sin DPAPI: la clave se conserva tal cual
    ciphertext = vault.MAGIC + Fernet(key).encrypt(b"documento previo")
    web = _web_app(monkeypatch, tmp_path)
    assert (data / "vault.key").read_bytes() == key
    assert vault.decrypt_bytes(ciphertext) == b"documento previo"
    assert web.data_dir == data


def test_corrupt_document_download_fails_safely(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    assigned, _other, _case, doc = _seed_case(web)
    with web.connect_db() as db:
        path = Path(db.execute("SELECT stored_path FROM documents WHERE id = ?", (doc,)).fetchone()[0])
    path.write_bytes(vault.MAGIC + b"basura-no-valida")
    response = _client_as(web, assigned).get(f"/documents/{doc}")
    assert response.status_code == 500
    assert b"Traceback" not in response.data and b"InvalidToken" not in response.data


# --------------------------------------------------------------------- auditoría
def test_audit_records_logins_downloads_and_denials_without_secrets(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    assigned, other, case_id, doc = _seed_case(web)
    client = web.app.test_client()
    with client.session_transaction() as s:
        s["csrf_token"] = CSRF
    client.post("/login", data={"username": "asignada", "password": "incorrecta-xyz", "csrf_token": CSRF})
    client.post("/login", data={"username": "asignada", "password": PASSWORD, "csrf_token": CSRF})
    client.get(f"/documents/{doc}")
    _client_as(web, other).get(f"/case/{case_id}")
    with web.connect_db() as db:
        rows = db.execute("SELECT action, result, username, resource_type, reason, details FROM audit_log").fetchall()
    actions = {(r["action"], r["result"]) for r in rows}
    assert {("auth.login", "denied"), ("auth.login", "ok"), ("documents.download", "ok"),
            ("access.denied", "denied")} <= actions
    dump = " ".join(" ".join(str(v) for v in r) for r in rows)
    assert "incorrecta-xyz" not in dump and PASSWORD not in dump
    denied = [r for r in rows if r["action"] == "access.denied"][0]
    assert denied["resource_type"] == "case" and "alcance" in denied["reason"]
